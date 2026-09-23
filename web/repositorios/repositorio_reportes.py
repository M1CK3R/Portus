"""Repositorio de reportes de corrida (SPECS §16.3 [PROP], §17.1).

Cada reporte generado se persiste con su etiqueta, rango, política activa y
las 8 métricas en JSON, para poder recuperarlo y compararlo con la Fase 3.
"""

import json
import sqlite3
from typing import cast

from web.modelos.reporte import Reporte
from web.repositorios.conexion_bd import ConexionBd, id_insertado

COLUMNAS_REPORTE = "id, etiqueta, inicio, fin, politica, resultado, generado_por, generado_en"


class RepositorioReportes:
    """Alta y lectura de reportes persistidos (§16.3)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def registrar(
        self,
        etiqueta: str,
        inicio: str,
        fin: str,
        politica: str,
        resultado: dict[str, object],
        generado_por: int | None,
        generado_en: str,
    ) -> int:
        """Inserta el reporte y devuelve su id (§16.3)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT INTO reporte (etiqueta, inicio, fin, politica, resultado, "
                "generado_por, generado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    etiqueta,
                    inicio,
                    fin,
                    politica,
                    json.dumps(resultado, ensure_ascii=False),
                    generado_por,
                    generado_en,
                ),
            )
            self._bd.conexion.commit()
        return id_insertado(cursor)

    def buscar_por_id(self, reporte_id: int) -> Reporte | None:
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_REPORTE} FROM reporte WHERE id = ?",
                (reporte_id,),
            ).fetchone()
        return _reporte_de_fila(fila) if fila is not None else None


def _reporte_de_fila(fila: sqlite3.Row) -> Reporte:
    generado_por = fila[6]
    return Reporte(
        id=int(fila[0]),
        etiqueta=str(fila[1]),
        inicio=str(fila[2]),
        fin=str(fila[3]),
        politica=str(fila[4]),
        resultado=cast(dict[str, object], json.loads(str(fila[5]))),
        generado_por=None if generado_por is None else int(generado_por),
        generado_en=str(fila[7]),
    )
