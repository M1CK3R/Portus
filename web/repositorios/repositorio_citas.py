"""Repositorio de citas y franjas (SPECS §11, §17.1).

La garita marca aquí la ventana (A11) y el cierre del turno el cumplimiento;
la cita con la que se presenta el vehículo y las demás transiciones de estado
viven en ``repositorio_ciclo_cita`` (§11.2). La Etapa 6 agrega la gestión de
agenda de TERMINAL (§14.5) y la Etapa 10 la solicitud desde el bot:
contenedores citables, ocupación de franjas, reserva transaccional (§11.3) y
recordatorios (§11.5).
"""

import sqlite3
from dataclasses import dataclass

from web.modelos.cita import CAPACIDAD_FRANJA, OcupacionFranja, fin_de_franja
from web.repositorios.conexion_bd import ConexionBd, id_insertado

COLUMNAS_CITA = (
    "cita.id, cita.manifiesto_id, cita.transportista_id, cita.franja_fecha, "
    "cita.franja_inicio, cita.estado, cita.cumplida_en_ventana, cita.creada_en, "
    "franja.fin, franja.bloqueada"
)

SIN_TURNO_QUE_LA_USE = "NOT EXISTS (SELECT 1 FROM turno WHERE turno.cita_id = cita.id)"
"""Condición SQL fija: la cita todavía no respaldó el ingreso de un vehículo."""

MOTIVO_SIN_CARGA = "SIN_CARGA"
MOTIVO_SIN_LEVANTE = "SIN_LEVANTE"
MOTIVO_CITA_VIGENTE = "CITA_VIGENTE"
MOTIVO_FRANJA_BLOQUEADA = "FRANJA_BLOQUEADA"
MOTIVO_FRANJA_SIN_CAPACIDAD = "FRANJA_SIN_CAPACIDAD"
"""Motivos de rechazo de la reserva (§11.1); el bot los traduce a texto."""


@dataclass(frozen=True)
class CitaConFranja:
    """Cita con el fin de su franja, necesario para la ventana (§11.1 regla 6)."""

    id: int
    manifiesto_id: int
    transportista_id: int
    franja_fecha: str
    franja_inicio: str
    estado: str
    cumplida_en_ventana: bool | None
    creada_en: str
    franja_fin: str
    franja_bloqueada: bool


@dataclass(frozen=True)
class CitaAgenda:
    """Cita de la agenda del día con identidad para la pestaña Citas (§14.5)."""

    id: int
    manifiesto_id: int
    transportista_id: int
    transportista: str
    vehiculo: str
    contenedor: str
    estado: str
    cumplida_en_ventana: bool | None
    en_uso: bool = False
    """Un turno ya la usó en garita: TERMINAL no puede cancelarla ni moverla."""


@dataclass(frozen=True)
class ContenedorCitable:
    """Contenedor propio con levante y sin cita vigente (§15.2 ``/cita``)."""

    manifiesto_id: int
    contenedor_id: str
    tipo_op: str


@dataclass(frozen=True)
class CitaDelTransportista:
    """Fila de ``/miscitas``: contenedor, franja y estado (§15.2)."""

    id: int
    contenedor_id: str
    fecha: str
    inicio: str
    fin: str
    estado: str


@dataclass(frozen=True)
class CitaPorRecordar:
    """Cita programada sin recordatorio todavía (§11.5)."""

    id: int
    transportista_id: int
    contenedor_id: str
    fecha: str
    inicio: str
    fin: str


@dataclass(frozen=True)
class ResultadoReserva:
    """Desenlace de la reserva de ``/cita``: id de la cita o motivo del rechazo."""

    cita_id: int | None
    motivo: str = ""


@dataclass(frozen=True)
class FranjaAgenda:
    """Franja del día con su capacidad, bloqueo y citas asignadas (§14.5)."""

    fecha: str
    inicio: str
    fin: str
    capacidad: int
    bloqueada: bool
    citas: list[CitaAgenda]


class RepositorioCitas:
    """Lecturas de la agenda para la validación de garita (§9.4 paso 4)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def marcar_ventana(self, cita_id: int, dentro_de_ventana: bool) -> None:
        """Fija ``cumplida_en_ventana`` al autorizar el ingreso (A11 [DEC])."""
        with self._bd.candado:
            self._bd.conexion.execute(
                "UPDATE cita SET cumplida_en_ventana = ? WHERE id = ?",
                (1 if dentro_de_ventana else 0, cita_id),
            )
            self._bd.conexion.commit()

    def marcar_cumplida(self, cita_id: int) -> None:
        """Al cerrarse el turno la cita queda ``cumplida`` (§11.2, §8.6)."""
        with self._bd.candado:
            self._bd.conexion.execute(
                "UPDATE cita SET estado = 'cumplida' WHERE id = ? AND estado = 'programada'",
                (cita_id,),
            )
            self._bd.conexion.commit()

    def crear(
        self, manifiesto_id: int, transportista_id: int, fecha: str, inicio: str, creada_en: str
    ) -> int:
        """Alta de prueba/semilla con franja de 15 min (§11.1)."""
        with self._bd.candado:
            self._bd.conexion.execute(
                "INSERT OR IGNORE INTO franja (fecha, inicio, fin) VALUES (?, ?, ?)",
                (fecha, inicio, fin_de_franja(inicio)),
            )
            self._bd.conexion.execute(
                "INSERT INTO cita (manifiesto_id, transportista_id, franja_fecha, "
                "franja_inicio, estado, creada_en) VALUES (?, ?, ?, ?, 'programada', ?)",
                (manifiesto_id, transportista_id, fecha, inicio, creada_en),
            )
            cursor = self._bd.conexion.execute(
                "SELECT id FROM cita WHERE manifiesto_id = ? AND estado = 'programada'",
                (manifiesto_id,),
            )
            id_cita = int(cursor.fetchone()[0])
            self._bd.conexion.commit()
        return id_cita

    # ----------------------------------------------------------- Etapa 6 §14.5

    def agenda_de_fecha(self, fecha: str) -> list[FranjaAgenda]:
        """Franjas del día con capacidad, bloqueo y citas asignadas (§14.5).

        Cada cita trae transportista, vehículo y contenedor para la lista de la
        franja. Las franjas se ordenan por hora de inicio. El vehículo es el
        del turno si la cita ya se usó; antes se listan los del transportista
        en una sola fila (un JOIN directo repetía la cita por cada vehículo).
        """
        with self._bd.candado:
            franjas = self._bd.conexion.execute(
                "SELECT fecha, inicio, fin, capacidad, bloqueada FROM franja "
                "WHERE fecha = ? ORDER BY inicio",
                (fecha,),
            ).fetchall()
            citas = self._bd.conexion.execute(
                "SELECT cita.id, cita.manifiesto_id, cita.transportista_id, "
                "usuario.nombre_mostrado, COALESCE("
                "(SELECT vehiculo.identificador FROM turno "
                "JOIN vehiculo ON vehiculo.id = turno.vehiculo_id "
                "WHERE turno.cita_id = cita.id ORDER BY turno.id DESC LIMIT 1), "
                "(SELECT GROUP_CONCAT(vehiculo.identificador, ', ') FROM vehiculo "
                "WHERE vehiculo.transportista_id = cita.transportista_id)), "
                "manifiesto.contenedor_id, cita.estado, cita.cumplida_en_ventana, "
                "cita.franja_inicio, "
                "EXISTS (SELECT 1 FROM turno WHERE turno.cita_id = cita.id) "
                "FROM cita JOIN usuario ON cita.transportista_id = usuario.id "
                "JOIN manifiesto ON cita.manifiesto_id = manifiesto.id "
                "WHERE cita.franja_fecha = ? ORDER BY cita.franja_inicio, cita.id",
                (fecha,),
            ).fetchall()
        por_franja: dict[str, list[CitaAgenda]] = {}
        for fila in citas:
            ventana = fila[7]
            por_franja.setdefault(str(fila[8]), []).append(
                CitaAgenda(
                    id=int(fila[0]),
                    manifiesto_id=int(fila[1]),
                    transportista_id=int(fila[2]),
                    transportista=str(fila[3]),
                    vehiculo="" if fila[4] is None else str(fila[4]),
                    contenedor=str(fila[5]),
                    estado=str(fila[6]),
                    cumplida_en_ventana=None if ventana is None else bool(ventana),
                    en_uso=bool(fila[9]),
                )
            )
        return [
            FranjaAgenda(
                fecha=str(f[0]),
                inicio=str(f[1]),
                fin=str(f[2]),
                capacidad=int(f[3]),
                bloqueada=bool(f[4]),
                citas=por_franja.get(str(f[1]), []),
            )
            for f in franjas
        ]

    def buscar_por_id(self, cita_id: int) -> CitaConFranja | None:
        """Cita con su franja para reprogramar/cancelar (§14.5)."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_CITA} FROM cita JOIN franja "
                "ON cita.franja_fecha = franja.fecha AND cita.franja_inicio = franja.inicio "
                "WHERE cita.id = ?",
                (cita_id,),
            ).fetchone()
        return cita_de_fila(fila) if fila is not None else None

    def cancelar(self, cita_id: int) -> bool:
        """Marca la cita como cancelada (§11.4); solo programada y sin turno que la use."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE cita SET estado = 'cancelada' WHERE id = ? AND estado = 'programada' "
                f"AND {SIN_TURNO_QUE_LA_USE}",
                (cita_id,),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def reprogramar(self, cita_id: int, fecha: str, inicio: str) -> tuple[bool, str]:
        """Mueve la cita a otra franja con capacidad (§11.4, §14.5).

        Verifica capacidad (= 2) y que la franja no esté bloqueada antes de
        mover; devuelve (ok, motivo). La nueva franja se crea si no existe y
        el recordatorio ya enviado se descarta: la ventana nueva tiene el suyo.
        """
        with self._bd.candado:
            conexion = self._bd.conexion
            conexion.execute("BEGIN IMMEDIATE")
            try:
                conexion.execute(
                    "INSERT OR IGNORE INTO franja (fecha, inicio, fin) VALUES (?, ?, ?)",
                    (fecha, inicio, fin_de_franja(inicio)),
                )
                bloqueada = conexion.execute(
                    "SELECT bloqueada FROM franja WHERE fecha = ? AND inicio = ?",
                    (fecha, inicio),
                ).fetchone()
                if bloqueada is not None and bool(bloqueada[0]):
                    conexion.rollback()
                    return (False, "FRANJA_BLOQUEADA")
                asignadas = conexion.execute(
                    "SELECT COUNT(*) FROM cita WHERE franja_fecha = ? AND franja_inicio = ? "
                    "AND estado = 'programada'",
                    (fecha, inicio),
                ).fetchone()[0]
                if int(asignadas) >= CAPACIDAD_FRANJA:
                    conexion.rollback()
                    return (False, "FRANJA_SIN_CAPACIDAD")
                cursor = conexion.execute(
                    "UPDATE cita SET franja_fecha = ?, franja_inicio = ? "
                    f"WHERE id = ? AND estado = 'programada' AND {SIN_TURNO_QUE_LA_USE}",
                    (fecha, inicio, cita_id),
                )
                if cursor.rowcount != 1:
                    conexion.rollback()
                    return (False, "CITA_NO_PROGRAMADA")
                conexion.execute("DELETE FROM recordatorio_cita WHERE cita_id = ?", (cita_id,))
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise
        return (True, "")

    def bloquear_franja(self, fecha: str, inicio: str) -> bool:
        """Bloquea una franja para impedir nuevas citas (§11.4, §14.5).

        Las franjas nacen al reservarse la primera cita; una franja aún vacía
        se crea aquí para poder bloquearla antes de que alguien la pida.
        """
        with self._bd.candado:
            self._bd.conexion.execute(
                "INSERT OR IGNORE INTO franja (fecha, inicio, fin) VALUES (?, ?, ?)",
                (fecha, inicio, fin_de_franja(inicio)),
            )
            cursor = self._bd.conexion.execute(
                "UPDATE franja SET bloqueada = 1 WHERE fecha = ? AND inicio = ?",
                (fecha, inicio),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def cumplimiento_de_fecha(self, fecha: str) -> tuple[int, int]:
        """(cumplidas_en_ventana, total) del día (§14.5 indicador, §11.1 regla 8).

        Cuentan las citas con cumplimiento registrado: la ventana se fija al
        presentarse en garita y la vencida queda en 0; las programadas aún por
        llegar y las canceladas antes de presentarse no tienen resultado.
        """
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT SUM(CASE WHEN cumplida_en_ventana = 1 THEN 1 ELSE 0 END), COUNT(*) "
                "FROM cita WHERE franja_fecha = ? AND cumplida_en_ventana IS NOT NULL",
                (fecha,),
            ).fetchone()
        cumplidas = 0 if fila[0] is None else int(fila[0])
        total = int(fila[1])
        return (cumplidas, total)

    # ---------------------------------------------------- Etapa 10 (bot §15.2)

    def contenedores_citables(self, transportista_id: int) -> list[ContenedorCitable]:
        """Contenedores del transportista con levante y sin cita vigente (§11.1 reglas 3 y 4).

        El filtro de propiedad va en el SQL (PY-3): solo manifiestos cuyo
        ``transportista_id`` es el del chat vinculado.
        """
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT manifiesto.id, manifiesto.contenedor_id, manifiesto.tipo_op "
                "FROM manifiesto WHERE manifiesto.transportista_id = ? "
                "AND manifiesto.estado_documental = 'levante_otorgado' "
                "AND manifiesto.estado_operativo = 'sin_turno' "
                "AND NOT EXISTS (SELECT 1 FROM cita WHERE cita.manifiesto_id = manifiesto.id "
                "AND cita.estado = 'programada') "
                "ORDER BY manifiesto.contenedor_id, manifiesto.id",
                (transportista_id,),
            ).fetchall()
        return [
            ContenedorCitable(
                manifiesto_id=int(fila[0]), contenedor_id=str(fila[1]), tipo_op=str(fila[2])
            )
            for fila in filas
        ]

    def ocupacion(self, fechas: list[str]) -> dict[tuple[str, str], OcupacionFranja]:
        """Bloqueo y citas programadas de las franjas existentes de esas fechas (§11.3)."""
        marcadores = ", ".join("?" for _ in fechas)
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT franja.fecha, franja.inicio, franja.bloqueada, "
                "(SELECT COUNT(*) FROM cita WHERE cita.franja_fecha = franja.fecha "
                "AND cita.franja_inicio = franja.inicio AND cita.estado = 'programada') "
                f"FROM franja WHERE franja.fecha IN ({marcadores})",
                tuple(fechas),
            ).fetchall()
        return {
            (str(fila[0]), str(fila[1])): OcupacionFranja(
                bloqueada=bool(fila[2]), asignadas=int(fila[3])
            )
            for fila in filas
        }

    def reservar(
        self, manifiesto_id: int, transportista_id: int, fecha: str, inicio: str, creada_en: str
    ) -> ResultadoReserva:
        """Crea la cita volviendo a verificar todo dentro de una transacción (§11.3 paso 4).

        Entre el ofrecimiento y la confirmación pasan segundos: otro
        transportista pudo llenar la franja, TERMINAL pudo bloquearla o el
        manifiesto pudo cambiar. ``BEGIN IMMEDIATE`` toma el candado de
        escritura antes de leer, así dos confirmaciones simultáneas (web y
        bot son procesos distintos) no sobreasignan la franja (BD-4).
        """
        with self._bd.candado:
            conexion = self._bd.conexion
            conexion.execute("BEGIN IMMEDIATE")
            try:
                motivo = _motivo_de_rechazo_de_reserva(
                    conexion, manifiesto_id, transportista_id, fecha, inicio
                )
                if motivo:
                    conexion.rollback()
                    return ResultadoReserva(cita_id=None, motivo=motivo)
                conexion.execute(
                    "INSERT OR IGNORE INTO franja (fecha, inicio, fin) VALUES (?, ?, ?)",
                    (fecha, inicio, fin_de_franja(inicio)),
                )
                cursor = conexion.execute(
                    "INSERT INTO cita (manifiesto_id, transportista_id, franja_fecha, "
                    "franja_inicio, estado, creada_en) VALUES (?, ?, ?, ?, 'programada', ?)",
                    (manifiesto_id, transportista_id, fecha, inicio, creada_en),
                )
                cita_id = id_insertado(cursor)
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise
        return ResultadoReserva(cita_id=cita_id)

    def del_transportista(
        self, transportista_id: int, desde_fecha: str
    ) -> list[CitaDelTransportista]:
        """Citas del transportista desde una fecha, más las programadas atrasadas (§15.2)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT cita.id, manifiesto.contenedor_id, cita.franja_fecha, "
                "cita.franja_inicio, franja.fin, cita.estado "
                "FROM cita JOIN manifiesto ON manifiesto.id = cita.manifiesto_id "
                "JOIN franja ON franja.fecha = cita.franja_fecha "
                "AND franja.inicio = cita.franja_inicio "
                "WHERE cita.transportista_id = ? "
                "AND (cita.franja_fecha >= ? OR cita.estado = 'programada') "
                "ORDER BY cita.franja_fecha, cita.franja_inicio, cita.id",
                (transportista_id, desde_fecha),
            ).fetchall()
        return [
            CitaDelTransportista(
                id=int(fila[0]),
                contenedor_id=str(fila[1]),
                fecha=str(fila[2]),
                inicio=str(fila[3]),
                fin=str(fila[4]),
                estado=str(fila[5]),
            )
            for fila in filas
        ]

    def por_recordar(self, fechas: list[str]) -> list[CitaPorRecordar]:
        """Citas programadas de esas fechas que aún no tienen recordatorio (§11.5)."""
        marcadores = ", ".join("?" for _ in fechas)
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT cita.id, cita.transportista_id, manifiesto.contenedor_id, "
                "cita.franja_fecha, cita.franja_inicio, franja.fin "
                "FROM cita JOIN manifiesto ON manifiesto.id = cita.manifiesto_id "
                "JOIN franja ON franja.fecha = cita.franja_fecha "
                "AND franja.inicio = cita.franja_inicio "
                f"WHERE cita.estado = 'programada' AND cita.franja_fecha IN ({marcadores}) "
                "AND NOT EXISTS (SELECT 1 FROM recordatorio_cita "
                "WHERE recordatorio_cita.cita_id = cita.id) "
                "ORDER BY cita.franja_fecha, cita.franja_inicio",
                tuple(fechas),
            ).fetchall()
        return [
            CitaPorRecordar(
                id=int(fila[0]),
                transportista_id=int(fila[1]),
                contenedor_id=str(fila[2]),
                fecha=str(fila[3]),
                inicio=str(fila[4]),
                fin=str(fila[5]),
            )
            for fila in filas
        ]

    def registrar_recordatorio(self, cita_id: int, notificacion_id: int, ts: str) -> bool:
        """Marca el recordatorio de la cita; False si ya existía (una vez por ventana)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT OR IGNORE INTO recordatorio_cita (cita_id, notificacion_id, ts) "
                "VALUES (?, ?, ?)",
                (cita_id, notificacion_id, ts),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0


def _motivo_de_rechazo_de_reserva(
    conexion: sqlite3.Connection,
    manifiesto_id: int,
    transportista_id: int,
    fecha: str,
    inicio: str,
) -> str:
    """Revalida propiedad, levante, cita única y capacidad (§11.1); "" si procede."""
    manifiesto = conexion.execute(
        "SELECT estado_documental, estado_operativo FROM manifiesto "
        "WHERE id = ? AND transportista_id = ?",
        (manifiesto_id, transportista_id),
    ).fetchone()
    if manifiesto is None:
        return MOTIVO_SIN_CARGA
    if str(manifiesto[0]) != "levante_otorgado" or str(manifiesto[1]) != "sin_turno":
        return MOTIVO_SIN_LEVANTE
    vigente = conexion.execute(
        "SELECT 1 FROM cita WHERE manifiesto_id = ? AND estado = 'programada'",
        (manifiesto_id,),
    ).fetchone()
    if vigente is not None:
        return MOTIVO_CITA_VIGENTE
    franja = conexion.execute(
        "SELECT bloqueada, (SELECT COUNT(*) FROM cita WHERE franja_fecha = ? "
        "AND franja_inicio = ? AND estado = 'programada') "
        "FROM franja WHERE fecha = ? AND inicio = ?",
        (fecha, inicio, fecha, inicio),
    ).fetchone()
    if franja is not None and bool(franja[0]):
        return MOTIVO_FRANJA_BLOQUEADA
    if franja is not None and int(franja[1]) >= CAPACIDAD_FRANJA:
        return MOTIVO_FRANJA_SIN_CAPACIDAD
    return ""


def cita_de_fila(fila: sqlite3.Row) -> CitaConFranja:
    """Fila de ``COLUMNAS_CITA`` → modelo (lo comparte el repositorio del ciclo)."""
    ventana = fila[6]
    return CitaConFranja(
        id=int(fila[0]),
        manifiesto_id=int(fila[1]),
        transportista_id=int(fila[2]),
        franja_fecha=str(fila[3]),
        franja_inicio=str(fila[4]),
        estado=str(fila[5]),
        cumplida_en_ventana=None if ventana is None else bool(ventana),
        creada_en=str(fila[7]),
        franja_fin=str(fila[8]),
        franja_bloqueada=bool(fila[9]),
    )
