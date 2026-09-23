"""Repositorio de notificaciones para el transportista (SPECS §10.7, §15.3, §17.1).

La lógica del turno **genera** las notificaciones automáticas y las deja
persistidas; el bot de mensajería (Etapa 10) las entrega por Telegram y las
marca ``entregado``. Mientras tanto se publican también en ``portus/srv/*``
para que el tablero las muestre en vivo.
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import cast

from web.repositorios.conexion_bd import ConexionBd, id_insertado


@dataclass(frozen=True)
class Notificacion:
    """Una notificación pendiente o entregada al transportista (§15.3)."""

    id: int
    transportista_id: int
    tipo: str
    payload: dict[str, object]
    ts: str
    entregado: bool


class RepositorioNotificaciones:
    """Las 9 notificaciones automáticas nacen aquí (§15.3)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def crear(self, transportista_id: int, tipo: str, payload: dict[str, object], ts: str) -> int:
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT INTO notificacion (transportista_id, tipo, payload, ts) "
                "VALUES (?, ?, ?, ?)",
                (transportista_id, tipo, json.dumps(payload, ensure_ascii=False), ts),
            )
            self._bd.conexion.commit()
        return id_insertado(cursor)

    def pendientes(self, transportista_id: int) -> list[Notificacion]:
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT id, transportista_id, tipo, payload, ts, entregado FROM notificacion "
                "WHERE transportista_id = ? AND entregado = 0 ORDER BY id",
                (transportista_id,),
            ).fetchall()
        return [_notificacion_de_fila(fila) for fila in filas]


def _notificacion_de_fila(fila: sqlite3.Row) -> Notificacion:
    return Notificacion(
        id=int(fila[0]),
        transportista_id=int(fila[1]),
        tipo=str(fila[2]),
        payload=cast(dict[str, object], json.loads(str(fila[3]))),
        ts=str(fila[4]),
        entregado=bool(fila[5]),
    )
