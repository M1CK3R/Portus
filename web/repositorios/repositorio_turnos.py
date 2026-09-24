"""Repositorio de turnos y su línea de tiempo (SPECS §8, §14.2)."""

import json
import sqlite3
from dataclasses import dataclass
from typing import cast

from web.modelos.turno import EstadoTurno, EventoLineaTiempo, Turno
from web.repositorios.conexion_bd import ConexionBd, id_insertado

COLUMNAS_TURNO = (
    "id, vehiculo_id, manifiesto_id, cita_id, tipo_op, estado, "
    "estado_previo_retencion, posicion_patio, nivel, peso_entrada_g, peso_salida_g, "
    "canal, dentro_de_ventana, creado_en, cerrado_en, motivo_anulacion"
)


class RepositorioTurnos:
    """Ciclo de vida persistido del turno; la validación de transición vive en el servicio."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def crear(
        self,
        vehiculo_id: int,
        manifiesto_id: int,
        cita_id: int | None,
        tipo_op: str,
        canal: str,
        dentro_de_ventana: bool,
        creado_en: str,
    ) -> int:
        """Crea el turno en ``EnGarita``: solo la autorización crea turno (§8.2 regla 1, A1)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT INTO turno (vehiculo_id, manifiesto_id, cita_id, tipo_op, estado, "
                "canal, dentro_de_ventana, creado_en) VALUES (?, ?, ?, ?, 'EnGarita', ?, ?, ?)",
                (
                    vehiculo_id,
                    manifiesto_id,
                    cita_id,
                    tipo_op,
                    canal,
                    1 if dentro_de_ventana else 0,
                    creado_en,
                ),
            )
            self._bd.conexion.commit()
        return id_insertado(cursor)

    def activo_de_vehiculo(self, vehiculo_id: int) -> Turno | None:
        """Turno no final del vehículo; None si no hay operación en curso."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_TURNO} FROM turno "
                "WHERE vehiculo_id = ? AND estado NOT IN ('Cerrado', 'Anulado') "
                "ORDER BY id DESC LIMIT 1",
                (vehiculo_id,),
            ).fetchone()
        return _turno_de_fila(fila) if fila is not None else None

    def buscar_por_id(self, turno_id: int) -> Turno | None:
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_TURNO} FROM turno WHERE id = ?", (turno_id,)
            ).fetchone()
        return _turno_de_fila(fila) if fila is not None else None

    def actualizar_estado(
        self, turno_id: int, nuevo: EstadoTurno, estado_previo_retencion: str | None
    ) -> bool:
        """Aplica la transición persistida; el CHECK del esquema también la limita (BD-3)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE turno SET estado = ?, estado_previo_retencion = ? WHERE id = ?",
                (nuevo.value, estado_previo_retencion, turno_id),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def actualizar_datos(self, turno_id: int, campos: dict[str, str | int | None]) -> None:
        """Actualiza columnas concretas del turno (pesos, posición, cierre)."""
        permitidas = {
            "posicion_patio",
            "nivel",
            "peso_entrada_g",
            "peso_salida_g",
            "cerrado_en",
            "motivo_anulacion",
        }
        if not campos or any(clave not in permitidas for clave in campos):
            mensaje = f"campos fuera de la lista permitida {sorted(permitidas)}: {sorted(campos)}"
            raise ValueError(mensaje)
        asignaciones = ", ".join(f"{clave} = ?" for clave in campos)
        valores = tuple(campos.values())
        with self._bd.candado:
            self._bd.conexion.execute(
                f"UPDATE turno SET {asignaciones} WHERE id = ?", (*valores, turno_id)
            )
            self._bd.conexion.commit()

    def registrar_evento(
        self,
        turno_id: int,
        ts: str,
        origen: str,
        tipo: str,
        descripcion: str,
        valores: dict[str, object],
        seq: int | None,
    ) -> None:
        """Añade una entrada a la línea de tiempo del turno (§8, §14.2)."""
        with self._bd.candado:
            self._bd.conexion.execute(
                "INSERT INTO evento_turno (turno_id, ts, origen, tipo, descripcion, valores, seq) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    turno_id,
                    ts,
                    origen,
                    tipo,
                    descripcion,
                    json.dumps(valores, ensure_ascii=False),
                    seq,
                ),
            )
            self._bd.conexion.commit()

    def linea_de_tiempo(self, turno_id: int) -> list[EventoLineaTiempo]:
        """Línea de tiempo completa en orden, también para cerrados y anulados (§14.2)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT id, turno_id, ts, origen, tipo, descripcion, valores, seq "
                "FROM evento_turno WHERE turno_id = ? ORDER BY id",
                (turno_id,),
            ).fetchall()
        return [_evento_de_fila(fila) for fila in filas]

    def cerrados_en_rango(self, inicio: str, fin: str) -> list[tuple[str, str, str]]:
        """(creado_en, cerrado_en, tipo_op) de los turnos cerrados en el rango (§16.1 m4)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT creado_en, cerrado_en, tipo_op FROM turno "
                "WHERE estado = 'Cerrado' AND cerrado_en >= ? AND cerrado_en <= ? "
                "ORDER BY cerrado_en",
                (inicio, fin),
            ).fetchall()
        return [(str(f[0]), str(f[1]), str(f[2])) for f in filas]


@dataclass(frozen=True)
class FilaTurno:
    """Fila de listado con la identidad del vehículo para la pestaña Turnos (§14.2)."""

    id: int
    estado: str
    tipo_op: str
    identificador_vehiculo: str
    contenedor_id: str
    transportista: str
    posicion_patio: str | None
    peso_declarado_g: int
    peso_entrada_g: int | None
    peso_salida_g: int | None
    creado_en: str
    cerrado_en: str | None


class ListadoTurnos:
    """Consultas de listado para la pestaña Turnos (§14.2)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def listar(
        self,
        estados: tuple[str, ...] | None = None,
        *,
        tipo_op: str | None = None,
        desde: str | None = None,
        hasta: str | None = None,
        busqueda: str | None = None,
    ) -> list[FilaTurno]:
        """Lista con filtros opcionales (§14.2: estado, tipo, fecha, búsqueda).

        ``busqueda`` busca por contenedor o identificador de vehículo (LIKE).
        ``desde``/``hasta`` acota por ``creado_en`` (ISO 8601 UTC). Orden descendente.
        """
        sql = (
            "SELECT turno.id, turno.estado, turno.tipo_op, vehiculo.identificador, "
            "manifiesto.contenedor_id, usuario.nombre_mostrado, turno.posicion_patio, "
            "manifiesto.peso_declarado_g, turno.peso_entrada_g, turno.peso_salida_g, "
            "turno.creado_en, turno.cerrado_en "
            "FROM turno JOIN vehiculo ON turno.vehiculo_id = vehiculo.id "
            "JOIN manifiesto ON turno.manifiesto_id = manifiesto.id "
            "JOIN usuario ON usuario.id = manifiesto.transportista_id"
        )
        condiciones: list[str] = []
        parametros: list[object] = []
        if estados:
            marcadores = ", ".join("?" for _ in estados)
            condiciones.append(f"turno.estado IN ({marcadores})")
            parametros.extend(estados)
        if tipo_op:
            condiciones.append("turno.tipo_op = ?")
            parametros.append(tipo_op)
        if desde:
            condiciones.append("turno.creado_en >= ?")
            parametros.append(desde)
        if hasta:
            condiciones.append("turno.creado_en <= ?")
            parametros.append(hasta)
        if busqueda:
            condiciones.append("(manifiesto.contenedor_id LIKE ? OR vehiculo.identificador LIKE ?)")
            patron = f"%{busqueda}%"
            parametros.extend([patron, patron])
        if condiciones:
            sql += " WHERE " + " AND ".join(condiciones)
        sql += " ORDER BY turno.id DESC"
        with self._bd.candado:
            filas = self._bd.conexion.execute(sql, tuple(parametros)).fetchall()
        return [
            FilaTurno(
                id=int(fila[0]),
                estado=str(fila[1]),
                tipo_op=str(fila[2]),
                identificador_vehiculo=str(fila[3]),
                contenedor_id=str(fila[4]),
                transportista=str(fila[5]),
                posicion_patio=None if fila[6] is None else str(fila[6]),
                peso_declarado_g=int(fila[7]),
                peso_entrada_g=None if fila[8] is None else int(fila[8]),
                peso_salida_g=None if fila[9] is None else int(fila[9]),
                creado_en=str(fila[10]),
                cerrado_en=None if fila[11] is None else str(fila[11]),
            )
            for fila in filas
        ]


def _turno_de_fila(fila: sqlite3.Row) -> Turno:
    dentro = fila[12]
    return Turno(
        id=int(fila[0]),
        vehiculo_id=int(fila[1]),
        manifiesto_id=int(fila[2]),
        cita_id=None if fila[3] is None else int(fila[3]),
        tipo_op=str(fila[4]),
        estado=EstadoTurno(str(fila[5])),
        estado_previo_retencion=None if fila[6] is None else str(fila[6]),
        posicion_patio=None if fila[7] is None else str(fila[7]),
        nivel=None if fila[8] is None else int(fila[8]),
        peso_entrada_g=None if fila[9] is None else int(fila[9]),
        peso_salida_g=None if fila[10] is None else int(fila[10]),
        canal=str(fila[11]),
        dentro_de_ventana=None if dentro is None else bool(dentro),
        creado_en=str(fila[13]),
        cerrado_en=None if fila[14] is None else str(fila[14]),
        motivo_anulacion=None if fila[15] is None else str(fila[15]),
    )


def _evento_de_fila(fila: sqlite3.Row) -> EventoLineaTiempo:
    seq = fila[7]
    return EventoLineaTiempo(
        id=int(fila[0]),
        turno_id=int(fila[1]),
        ts=str(fila[2]),
        origen=str(fila[3]),
        tipo=str(fila[4]),
        descripcion=str(fila[5]),
        valores=cast(dict[str, object], json.loads(str(fila[6]))),
        seq=None if seq is None else int(seq),
    )
