"""Repositorio de intentos de ingreso rechazados (SPECS §8.2 regla 1, §9.4)."""

import sqlite3
from dataclasses import dataclass

from web.repositorios.conexion_bd import ConexionBd


@dataclass(frozen=True)
class IntentoIngreso:
    """Registro de un ingreso rechazado; no crea turno (§8.2 regla 1)."""

    id: int
    ts: str
    identificador: str
    vehiculo_id: int | None
    causa: str
    detalle: str


class RepositorioIntentos:
    """Bitácora de la validación de garita; alimenta la revisión de rechazos."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def registrar(
        self,
        ts: str,
        identificador: str,
        vehiculo_id: int | None,
        causa: str,
        detalle: str,
    ) -> None:
        """Persiste el intento con su causa exacta (§9.4)."""
        with self._bd.candado:
            self._bd.conexion.execute(
                "INSERT INTO intento_ingreso (ts, identificador, vehiculo_id, causa, detalle) "
                "VALUES (?, ?, ?, ?, ?)",
                (ts, identificador, vehiculo_id, causa, detalle),
            )
            self._bd.conexion.commit()

    def recientes(self, limite: int = 50) -> list[IntentoIngreso]:
        """Los últimos intentos en orden temporal inverso (revisión E03/E11)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT id, ts, identificador, vehiculo_id, causa, detalle "
                "FROM intento_ingreso ORDER BY id DESC LIMIT ?",
                (limite,),
            ).fetchall()
        return [_intento_de_fila(fila) for fila in filas]


def _intento_de_fila(fila: sqlite3.Row) -> IntentoIngreso:
    vehiculo_id = fila[3]
    return IntentoIngreso(
        id=int(fila[0]),
        ts=str(fila[1]),
        identificador=str(fila[2]),
        vehiculo_id=None if vehiculo_id is None else int(vehiculo_id),
        causa=str(fila[4]),
        detalle=str(fila[5]),
    )
