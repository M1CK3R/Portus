"""Repositorio de trabajos de grúa (SPECS §12.5.1): cola por turno en el servidor.

El servidor planifica la cola del turno (depósito, retiro con sus remociones),
la envía al controlador como ``JOB`` (§4.4) y la actualiza **solo** con las
confirmaciones físicas ``GRU``/``PAT`` (§8.2 regla 2): un aborto devuelve el
trabajo a la cola sin tocar el inventario (§12.3). El ciclo de grúa registrado
(§12.6) persiste aquí también: es la fuente de las métricas 1-3 (§16.1) y de
la gráfica de la pestaña Grúa.
"""

import sqlite3

from web.modelos.ciclo_grua import CicloGrua, ResultadoCiclo
from web.modelos.trabajos import EstadoTrabajo, TipoTrabajo, Trabajo
from web.repositorios.conexion_bd import ConexionBd, id_insertado

COLUMNAS_TRABAJO = (
    "id, turno_id, tipo, contenedor_id, origen, destino, nivel, estado, orden, creado_en"
)

COLUMNAS_CICLO = (
    "id, turno_id, trabajo_id, tipo, ts_inicio, ts_fin, distancia_traslacion, resultado, creado_en"
)


class RepositorioTrabajos:
    """Plan de trabajos del turno: el retiro no inicia hasta completar remociones (§12.5)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def planificar(
        self, turno_id: int, trabajos: list[tuple[TipoTrabajo, str, str, str, int]], creado_en: str
    ) -> list[Trabajo]:
        """Alta en orden; ``trabajos`` trae (tipo, contenedor, origen, destino, nivel)."""
        with self._bd.candado:
            conexion = self._bd.conexion
            conexion.execute("BEGIN IMMEDIATE")
            try:
                creados: list[Trabajo] = []
                for orden, (tipo, contenedor, origen, destino, nivel) in enumerate(trabajos):
                    cursor = conexion.execute(
                        "INSERT INTO trabajo_grua (turno_id, tipo, contenedor_id, origen, "
                        "destino, nivel, estado, orden, creado_en) "
                        "VALUES (?, ?, ?, ?, ?, ?, 'PENDIENTE', ?, ?)",
                        (
                            turno_id,
                            tipo.value,
                            contenedor,
                            origen,
                            destino,
                            nivel,
                            orden,
                            creado_en,
                        ),
                    )
                    creados.append(
                        Trabajo(
                            id=id_insertado(cursor),
                            turno_id=turno_id,
                            tipo=tipo,
                            contenedor_id=contenedor,
                            origen=origen,
                            destino=destino,
                            nivel=nivel,
                            estado=EstadoTrabajo.PENDIENTE,
                            orden=orden,
                            creado_en=creado_en,
                        )
                    )
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise
        return creados

    def del_turno(self, turno_id: int) -> list[Trabajo]:
        """Plan completo del turno en orden de atención (§12.5)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_TRABAJO} FROM trabajo_grua WHERE turno_id = ? ORDER BY orden",
                (turno_id,),
            ).fetchall()
        return [_trabajo_de_fila(fila) for fila in filas]

    def en_curso(self, turno_id: int) -> Trabajo | None:
        """El trabajo en ejecución del turno, si lo hay."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_TRABAJO} FROM trabajo_grua "
                "WHERE turno_id = ? AND estado = 'EN_CURSO' ORDER BY orden LIMIT 1",
                (turno_id,),
            ).fetchone()
        return _trabajo_de_fila(fila) if fila is not None else None

    def en_curso_global(self) -> Trabajo | None:
        """El único trabajo en ejecución de la grúa (§12.6: una grúa, un curso)."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_TRABAJO} FROM trabajo_grua "
                "WHERE estado = 'EN_CURSO' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return _trabajo_de_fila(fila) if fila is not None else None

    def cola_pendiente(self) -> list[Trabajo]:
        """Trabajos pendientes de toda la grúa en orden de atención (§12.6)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_TRABAJO} FROM trabajo_grua "
                "WHERE estado = 'PENDIENTE' ORDER BY turno_id, orden"
            ).fetchall()
        return [_trabajo_de_fila(fila) for fila in filas]

    def en_curso_de_contenedor(self, contenedor_id: str) -> Trabajo | None:
        """Trabajo EN_CURSO de ese contenedor con turno no final (los GRU no traen vehículo)."""
        columnas = ", ".join(f"trabajo_grua.{columna}" for columna in COLUMNAS_TRABAJO.split(", "))
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {columnas} FROM trabajo_grua "
                "JOIN turno ON trabajo_grua.turno_id = turno.id "
                "WHERE trabajo_grua.contenedor_id = ? AND trabajo_grua.estado = 'EN_CURSO' "
                "AND turno.estado NOT IN ('Cerrado', 'Anulado') "
                "ORDER BY trabajo_grua.orden LIMIT 1",
                (contenedor_id,),
            ).fetchone()
        return _trabajo_de_fila(fila) if fila is not None else None

    def marcar_en_curso(self, trabajo_id: int) -> None:
        with self._bd.candado:
            self._bd.conexion.execute(
                "UPDATE trabajo_grua SET estado = 'EN_CURSO' WHERE id = ?", (trabajo_id,)
            )
            self._bd.conexion.commit()

    def completar(self, trabajo_id: int) -> None:
        with self._bd.candado:
            self._bd.conexion.execute(
                "UPDATE trabajo_grua SET estado = 'COMPLETADO' WHERE id = ?", (trabajo_id,)
            )
            self._bd.conexion.commit()

    def abortar(self, trabajo_id: int) -> None:
        """Un aborto devuelve el trabajo a la cola; el inventario no cambia (§12.3)."""
        with self._bd.candado:
            self._bd.conexion.execute(
                "UPDATE trabajo_grua SET estado = 'PENDIENTE' WHERE id = ?", (trabajo_id,)
            )
            self._bd.conexion.commit()

    def quedan_pendientes(self, turno_id: int) -> bool:
        """True si el turno aún tiene trabajos PENDIENTE o EN_CURSO (§12.5)."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT 1 FROM trabajo_grua "
                "WHERE turno_id = ? AND estado IN ('PENDIENTE', 'EN_CURSO') LIMIT 1",
                (turno_id,),
            ).fetchone()
        return fila is not None

    # --------------------------------------------------- ciclo de grúa §12.6

    def registrar_ciclo(
        self,
        turno_id: int,
        trabajo_id: int | None,
        tipo: TipoTrabajo,
        ts_inicio: str,
        ts_fin: str,
        distancia_traslacion: int,
        resultado: ResultadoCiclo,
        creado_en: str,
    ) -> int:
        """Persiste un ciclo de grúa completado o abortado (SPECS §12.6)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT INTO ciclo_grua (turno_id, trabajo_id, tipo, ts_inicio, ts_fin, "
                "distancia_traslacion, resultado, creado_en) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    turno_id,
                    trabajo_id,
                    tipo.value,
                    ts_inicio,
                    ts_fin,
                    distancia_traslacion,
                    resultado.value,
                    creado_en,
                ),
            )
            self._bd.conexion.commit()
        return id_insertado(cursor)

    def ciclos_ultimos(self, limite: int) -> list[CicloGrua]:
        """Últimos ``limite`` ciclos ordenados por ts_inicio descendente (§12.6)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_CICLO} FROM ciclo_grua ORDER BY ts_inicio DESC, id DESC LIMIT ?",
                (limite,),
            ).fetchall()
        return [_ciclo_de_fila(fila) for fila in filas]

    def ciclos_en_rango(self, inicio: str, fin: str) -> list[CicloGrua]:
        """Ciclos cuyo ``ts_inicio`` cae en [inicio, fin] (§16.3 reporte)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_CICLO} FROM ciclo_grua "
                "WHERE ts_inicio >= ? AND ts_inicio <= ? ORDER BY ts_inicio",
                (inicio, fin),
            ).fetchall()
        return [_ciclo_de_fila(fila) for fila in filas]


def _ciclo_de_fila(fila: sqlite3.Row) -> CicloGrua:
    trabajo_id = fila[2]
    return CicloGrua(
        id=int(fila[0]),
        turno_id=int(fila[1]),
        trabajo_id=None if trabajo_id is None else int(trabajo_id),
        tipo=TipoTrabajo(str(fila[3])),
        ts_inicio=str(fila[4]),
        ts_fin=str(fila[5]),
        distancia_traslacion=int(fila[6]),
        resultado=ResultadoCiclo(str(fila[7])),
        creado_en=str(fila[8]),
    )


def _trabajo_de_fila(fila: sqlite3.Row) -> Trabajo:
    return Trabajo(
        id=int(fila[0]),
        turno_id=int(fila[1]),
        tipo=TipoTrabajo(str(fila[2])),
        contenedor_id=str(fila[3]),
        origen=str(fila[4]),
        destino=str(fila[5]),
        nivel=int(fila[6]),
        estado=EstadoTrabajo(str(fila[7])),
        orden=int(fila[8]),
        creado_en=str(fila[9]),
    )
