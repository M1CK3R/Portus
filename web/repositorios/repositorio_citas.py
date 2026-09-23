"""Repositorio de citas y franjas (SPECS §11, §17.1).

En la Etapa 5 la agenda se lee para validar la garita (cita programada con su
franja) y se escribe para marcar la ventana (A11) y el cumplimiento al cerrar
el turno. El ofrecimiento de franjas y la gestión de agenda llegan con las
pestañas de citas (§11.3, §14.5).
"""

import sqlite3
from dataclasses import dataclass

from web.repositorios.conexion_bd import ConexionBd

COLUMNAS_CITA = (
    "cita.id, cita.manifiesto_id, cita.transportista_id, cita.franja_fecha, "
    "cita.franja_inicio, cita.estado, cita.cumplida_en_ventana, cita.creada_en, "
    "franja.fin, franja.bloqueada"
)


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

    def programada_de_manifiesto(self, manifiesto_id: int) -> CitaConFranja | None:
        """La cita ``programada`` del manifiesto; None si no tiene (→ SIN_CITA)."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_CITA} FROM cita JOIN franja "
                "ON cita.franja_fecha = franja.fecha AND cita.franja_inicio = franja.inicio "
                "WHERE cita.manifiesto_id = ? AND cita.estado = 'programada' "
                "ORDER BY cita.id LIMIT 1",
                (manifiesto_id,),
            ).fetchone()
        return _cita_de_fila(fila) if fila is not None else None

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
                (fecha, inicio, _fin_de_inicio(inicio)),
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
        franja. Las franjas se ordenan por hora de inicio.
        """
        with self._bd.candado:
            franjas = self._bd.conexion.execute(
                "SELECT fecha, inicio, fin, capacidad, bloqueada FROM franja "
                "WHERE fecha = ? ORDER BY inicio",
                (fecha,),
            ).fetchall()
            citas = self._bd.conexion.execute(
                "SELECT cita.id, cita.manifiesto_id, cita.transportista_id, "
                "usuario.nombre_mostrado, vehiculo.identificador, "
                "manifiesto.contenedor_id, cita.estado, cita.cumplida_en_ventana, "
                "cita.franja_inicio "
                "FROM cita JOIN usuario ON cita.transportista_id = usuario.id "
                "JOIN manifiesto ON cita.manifiesto_id = manifiesto.id "
                "LEFT JOIN vehiculo ON vehiculo.transportista_id = cita.transportista_id "
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
        return _cita_de_fila(fila) if fila is not None else None

    def cancelar(self, cita_id: int, ts: str) -> bool:
        """Marca la cita como cancelada (§11.4); solo si está programada."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE cita SET estado = 'cancelada' WHERE id = ? AND estado = 'programada'",
                (cita_id,),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def reprogramar(self, cita_id: int, fecha: str, inicio: str, ts: str) -> tuple[bool, str]:
        """Mueve la cita a otra franja con capacidad (§11.4, §14.5).

        Verifica capacidad (= 2) y que la franja no esté bloqueada antes de
        mover; devuelve (ok, motivo). La nueva franja se crea si no existe.
        """
        with self._bd.candado:
            conexion = self._bd.conexion
            conexion.execute("BEGIN IMMEDIATE")
            try:
                conexion.execute(
                    "INSERT OR IGNORE INTO franja (fecha, inicio, fin) VALUES (?, ?, ?)",
                    (fecha, inicio, _fin_de_inicio(inicio)),
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
                if int(asignadas) >= 2:  # §11.1: capacidad de 2
                    conexion.rollback()
                    return (False, "FRANJA_SIN_CAPACIDAD")
                cursor = conexion.execute(
                    "UPDATE cita SET franja_fecha = ?, franja_inicio = ? "
                    "WHERE id = ? AND estado = 'programada'",
                    (fecha, inicio, cita_id),
                )
                if cursor.rowcount != 1:
                    conexion.rollback()
                    return (False, "CITA_NO_PROGRAMADA")
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise
        _ = ts
        return (True, "")

    def bloquear_franja(self, fecha: str, inicio: str) -> bool:
        """Bloquea una franja para impedir nuevas citas (§11.4, §14.5)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE franja SET bloqueada = 1 WHERE fecha = ? AND inicio = ?",
                (fecha, inicio),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def cumplimiento_de_fecha(self, fecha: str) -> tuple[int, int]:
        """(cumplidas_en_ventana, total_del_dia) del día (§14.5 indicador)."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT SUM(CASE WHEN cumplida_en_ventana = 1 THEN 1 ELSE 0 END), COUNT(*) "
                "FROM cita WHERE franja_fecha = ? AND estado IN ('cumplida', 'vencida')",
                (fecha,),
            ).fetchone()
        cumplidas = 0 if fila[0] is None else int(fila[0])
        total = int(fila[1])
        return (cumplidas, total)

    def cumplimiento_en_rango(self, inicio: str, fin: str) -> tuple[int, int]:
        """(cumplidas_en_ventana, total) de las citas creadas en el rango (§16.1 m7)."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT SUM(CASE WHEN cumplida_en_ventana = 1 THEN 1 ELSE 0 END), COUNT(*) "
                "FROM cita WHERE creada_en >= ? AND creada_en <= ?",
                (inicio, fin),
            ).fetchone()
        cumplidas = 0 if fila[0] is None else int(fila[0])
        total = int(fila[1])
        return (cumplidas, total)


def _fin_de_inicio(inicio: str) -> str:
    """Fin de la franja: inicio + 15 minutos en formato HH:MM (§11.1 regla 1)."""
    hora, minuto = (int(parte) for parte in inicio.split(":"))
    total = hora * 60 + minuto + 15
    return f"{total // 60:02d}:{total % 60:02d}"


def _cita_de_fila(fila: sqlite3.Row) -> CitaConFranja:
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
