"""Repositorio de códigos de vinculación (SPECS §15.1, §17.1, A17)."""

import sqlite3

from web.modelos.vinculacion import CodigoVinculacion
from web.repositorios.conexion_bd import ConexionBd

COLUMNAS_CODIGO = "codigo, transportista_id, creado_en, expira_en, usado_en"


class RepositorioVinculos:
    """Ciclo de vida del código: crear, invalidar previos, consumir (§15.1)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def reemplazar_activo(self, codigo: CodigoVinculacion, instante: str) -> int:
        """Invalida los códigos activos previos del transportista e inserta el nuevo.

        Ambas escrituras van en una transacción (BD-4): si el INSERT falla, la
        invalidación no queda aplicada y el código anterior sigue vigente.
        Devuelve cuántos códigos previos se invalidaron.
        """
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE codigo_vinculacion SET expira_en = ? "
                "WHERE transportista_id = ? AND usado_en IS NULL AND expira_en > ?",
                (instante, codigo.transportista_id, instante),
            )
            invalidados = cursor.rowcount
            self._bd.conexion.execute(
                "INSERT INTO codigo_vinculacion "
                "(codigo, transportista_id, creado_en, expira_en, usado_en) "
                "VALUES (?, ?, ?, ?, NULL)",
                (codigo.codigo, codigo.transportista_id, codigo.creado_en, codigo.expira_en),
            )
            self._bd.conexion.commit()
        return invalidados

    def activos(self, instante: str) -> list[CodigoVinculacion]:
        """Códigos vigentes (no usados, no vencidos) para comparar en el servicio."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_CODIGO} FROM codigo_vinculacion "
                "WHERE usado_en IS NULL AND expira_en > ? ORDER BY creado_en",
                (instante,),
            ).fetchall()
        return [_codigo_de_fila(fila) for fila in filas]

    def marcar_usado(self, codigo: str, instante: str) -> None:
        """Consume un código de un solo uso; idempotente por el ``IS NULL`` (§15.1)."""
        with self._bd.candado:
            self._bd.conexion.execute(
                "UPDATE codigo_vinculacion SET usado_en = ? WHERE codigo = ? AND usado_en IS NULL",
                (instante, codigo),
            )
            self._bd.conexion.commit()

    def vinculados(self) -> set[int]:
        """Ids de transportistas con al menos un código consumido (vinculados, §15.1)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT DISTINCT transportista_id FROM codigo_vinculacion "
                "WHERE usado_en IS NOT NULL"
            ).fetchall()
        return {int(fila[0]) for fila in filas}


def _codigo_de_fila(fila: sqlite3.Row) -> CodigoVinculacion:
    """Convierte la fila tipada en el modelo del dominio (PY-2)."""
    usado = fila[4]
    return CodigoVinculacion(
        codigo=str(fila[0]),
        transportista_id=int(fila[1]),
        creado_en=str(fila[2]),
        expira_en=str(fila[3]),
        usado_en=None if usado is None else str(usado),
    )
