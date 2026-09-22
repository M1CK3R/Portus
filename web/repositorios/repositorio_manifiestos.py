"""Repositorio de manifiestos para los filtros de propiedad (SPECS §7.4, §7.5.2).

En la Etapa 4 la tabla existe para demostrar el aislamiento: NAVIERA recibe
solo sus filas porque el ``WHERE naviera_id = ?`` viaja dentro de la consulta
SQL, no se filtra en el cliente (§7.5.2). El ciclo documental completo se
implementa en la Etapa 5 (§9).
"""

import sqlite3
from dataclasses import dataclass

from web.repositorios.conexion_bd import ConexionBd

COLUMNAS_MANIFIESTO = (
    "id, contenedor_id, naviera_id, transportista_id, tipo_op, "
    "peso_declarado_g, estado_documental, estado_operativo, creado_en"
)


@dataclass(frozen=True)
class ResumenManifiesto:
    """Fila de listado; los estados viajan con los valores exactos de la BD."""

    id: int
    contenedor_id: str
    naviera_id: int
    transportista_id: int
    tipo_op: str
    peso_declarado_g: int
    estado_documental: str
    estado_operativo: str
    creado_en: str


class RepositorioManifiestos:
    """Consultas de solo lectura para la Etapa 4; la escritura llega en la 5."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def listar(self, naviera_id: int | None = None) -> list[ResumenManifiesto]:
        """Lista manifiestos; si viene ``naviera_id`` filtra en SQL (§7.5.2).

        El rol NAVIERA pasa siempre su propio id (el de la sesión); los roles
        TERMINAL, AGENTE y AUTORIDAD lo dejan en None y ven el listado
        completo (§7.4, fila «Ver manifiesto completo»).
        """
        if naviera_id is None:
            sql = f"SELECT {COLUMNAS_MANIFIESTO} FROM manifiesto ORDER BY id"
            parametros: tuple[object, ...] = ()
        else:
            sql = f"SELECT {COLUMNAS_MANIFIESTO} FROM manifiesto WHERE naviera_id = ? ORDER BY id"
            parametros = (naviera_id,)
        with self._bd.candado:
            filas = self._bd.conexion.execute(sql, parametros).fetchall()
        return [_resumen_de_fila(fila) for fila in filas]

    def crear_demo(
        self,
        contenedor_id: str,
        naviera_id: int,
        transportista_id: int,
        tipo_op: str,
        peso_declarado_g: int,
        creado_en: str,
    ) -> bool:
        """Alta mínima para pruebas y demostración del aislamiento (P11).

        No es parte del flujo de la Etapa 5: los formularios de creación de
        NAVIERA llegan con ella. Este método existe para poblar la bandeja
        desde las pruebas sin SQL suelto fuera de los repositorios (A-2).
        """
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT INTO manifiesto "
                "(contenedor_id, naviera_id, transportista_id, tipo_op, "
                " peso_declarado_g, estado_documental, estado_operativo, creado_en) "
                "VALUES (?, ?, ?, ?, ?, 'SIN_DECLARACION', 'PENDIENTE', ?)",
                (contenedor_id, naviera_id, transportista_id, tipo_op, peso_declarado_g, creado_en),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0


def _resumen_de_fila(fila: sqlite3.Row) -> ResumenManifiesto:
    """Convierte la fila tipada en el modelo del dominio (PY-2)."""
    return ResumenManifiesto(
        id=int(fila[0]),
        contenedor_id=str(fila[1]),
        naviera_id=int(fila[2]),
        transportista_id=int(fila[3]),
        tipo_op=str(fila[4]),
        peso_declarado_g=int(fila[5]),
        estado_documental=str(fila[6]),
        estado_operativo=str(fila[7]),
        creado_en=str(fila[8]),
    )
