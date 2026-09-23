"""Repositorio de solicitudes de levante (SPECS §9.1, §9.4, §17.1).

En la Etapa 5 solo se lee el estado del levante para la validación de garita;
los formularios de AGENTE y AUTORIDAD llegan con la Etapa 7 (§7.4).
"""

import sqlite3
from dataclasses import dataclass

from web.repositorios.conexion_bd import ConexionBd, id_insertado

COLUMNAS_LEVANTE = "id, manifiesto_id, estado, canal, motivo"

LEVANTE_SIN_SOLICITUD = "sin_solicitud"
LEVANTE_SOLICITADA = "solicitada"
LEVANTE_OTORGADO = "otorgada"
LEVANTE_RETENIDA = "retenida"


@dataclass(frozen=True)
class Levante:
    """Estado documental del levante de un manifiesto (§8.3, §9.1)."""

    id: int
    manifiesto_id: int
    estado: str
    canal: str | None
    motivo: str | None


class RepositorioLevantes:
    """Consulta del levante para el paso 3 de la validación (§9.4)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def de_manifiesto(self, manifiesto_id: int) -> Levante | None:
        """El levante del manifiesto; None si nunca hubo solicitud."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_LEVANTE} FROM solicitud_levante WHERE manifiesto_id = ?",
                (manifiesto_id,),
            ).fetchone()
        return _levante_de_fila(fila) if fila is not None else None

    def crear(self, manifiesto_id: int, estado: str, canal: str | None = None) -> int:
        """Alta de prueba/semilla del ciclo documental (§9.1)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT INTO solicitud_levante (manifiesto_id, estado, canal) VALUES (?, ?, ?)",
                (manifiesto_id, estado, canal),
            )
            self._bd.conexion.commit()
        return id_insertado(cursor)


def _levante_de_fila(fila: sqlite3.Row) -> Levante:
    canal = fila[3]
    motivo = fila[4]
    return Levante(
        id=int(fila[0]),
        manifiesto_id=int(fila[1]),
        estado=str(fila[2]),
        canal=None if canal is None else str(canal),
        motivo=None if motivo is None else str(motivo),
    )
