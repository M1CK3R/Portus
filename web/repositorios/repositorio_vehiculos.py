"""Repositorio de vehículos del catálogo de garita (SPECS §17.1, §9.4)."""

import sqlite3
from dataclasses import dataclass

from web.repositorios.conexion_bd import ConexionBd, id_insertado

COLUMNAS_VEHICULO = "id, identificador, transportista_id, tara_g"


@dataclass(frozen=True)
class Vehiculo:
    """Vehículo registrado; ``identificador`` es el que viaja en GAR.veh."""

    id: int
    identificador: str
    transportista_id: int
    tara_g: int
    """Tara del camión vacío en gramos (A4 [DEC])."""


class RepositorioVehiculos:
    """Consulta de identidad de la garita y alta del catálogo."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def buscar_por_identificador(self, identificador: str) -> Vehiculo | None:
        """Localiza el vehículo por la tarjeta/etiqueta que leyó la garita (§9.4)."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_VEHICULO} FROM vehiculo WHERE identificador = ?",
                (identificador,),
            ).fetchone()
        return _vehiculo_de_fila(fila) if fila is not None else None

    def buscar_por_id(self, id_vehiculo: int) -> Vehiculo | None:
        """Localiza el vehículo por su id (tara para la fórmula de pesaje, A4)."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_VEHICULO} FROM vehiculo WHERE id = ?", (id_vehiculo,)
            ).fetchone()
        return _vehiculo_de_fila(fila) if fila is not None else None

    def crear(self, identificador: str, transportista_id: int, tara_g: int) -> int:
        """Alta de catálogo para la semilla y las pruebas (A10, §19.3)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT INTO vehiculo (identificador, transportista_id, tara_g) VALUES (?, ?, ?)",
                (identificador, transportista_id, tara_g),
            )
            self._bd.conexion.commit()
        return id_insertado(cursor)


def _vehiculo_de_fila(fila: sqlite3.Row) -> Vehiculo:
    return Vehiculo(
        id=int(fila[0]),
        identificador=str(fila[1]),
        transportista_id=int(fila[2]),
        tara_g=int(fila[3]),
    )
