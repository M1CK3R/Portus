"""Repositorio de pesajes (SPECS §17.1 `pesaje`, evidencia de §10.4)."""

import sqlite3
from dataclasses import dataclass

from web.repositorios.conexion_bd import ConexionBd


@dataclass(frozen=True)
class Pesaje:
    """Un pesaje del turno; pesos en gramos y tolerancia como resultado."""

    id: int
    turno_id: int
    momento: str
    peso_g: int
    muestras: int
    meseta: bool
    dentro_tolerancia: bool
    ts: str


class RepositorioPesajes:
    """Historial de pesajes por turno; la evidencia de las RT01/RT02 sale de aquí."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def guardar(
        self,
        turno_id: int,
        momento: str,
        peso_g: int,
        muestras: int,
        meseta: bool,
        dentro_tolerancia: bool,
        ts: str,
    ) -> None:
        """Registra el pesaje confirmado por el controlador (§4.3 PES)."""
        with self._bd.candado:
            self._bd.conexion.execute(
                "INSERT INTO pesaje (turno_id, momento, peso_g, muestras, meseta, "
                "dentro_tolerancia, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    turno_id,
                    momento,
                    peso_g,
                    muestras,
                    1 if meseta else 0,
                    1 if dentro_tolerancia else 0,
                    ts,
                ),
            )
            self._bd.conexion.commit()

    def del_turno(self, turno_id: int) -> list[Pesaje]:
        """Pesajes del turno en orden; se conservan aunque pase a Retenido (§8.2 regla 3)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT id, turno_id, momento, peso_g, muestras, meseta, "
                "dentro_tolerancia, ts FROM pesaje WHERE turno_id = ? ORDER BY id",
                (turno_id,),
            ).fetchall()
        return [_pesaje_de_fila(fila) for fila in filas]


def _pesaje_de_fila(fila: sqlite3.Row) -> Pesaje:
    return Pesaje(
        id=int(fila[0]),
        turno_id=int(fila[1]),
        momento=str(fila[2]),
        peso_g=int(fila[3]),
        muestras=int(fila[4]),
        meseta=bool(fila[5]),
        dentro_tolerancia=bool(fila[6]),
        ts=str(fila[7]),
    )
