"""Repositorio de notificaciones para el transportista (SPECS §10.7, §15.3, §17.1).

La lógica del turno **genera** las notificaciones automáticas y las deja
persistidas (``web/servicios/notificador``); el bot de mensajería (Etapa 10)
las entrega por Telegram y las marca ``entregado``. Los reintentos y el
último error viven en ``entrega_notificacion`` (migración 007): sin internet
el aviso queda pendiente y sale cuando vuelve la conexión (§15.4).
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import cast

from web.repositorios.conexion_bd import ConexionBd, id_insertado

COLUMNAS_NOTIFICACION = (
    "notificacion.id, notificacion.transportista_id, notificacion.tipo, "
    "notificacion.payload, notificacion.ts, notificacion.entregado"
)


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

    def crear(
        self,
        transportista_id: int,
        tipo: str,
        payload: dict[str, object],
        ts: str,
        entregado: bool = False,
    ) -> int:
        """Alta del aviso; ``entregado`` solo para el que ya salió como respuesta del bot."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT INTO notificacion (transportista_id, tipo, payload, ts, entregado) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    transportista_id,
                    tipo,
                    json.dumps(payload, ensure_ascii=False),
                    ts,
                    1 if entregado else 0,
                ),
            )
            notificacion_id = id_insertado(cursor)
            if entregado:
                self._bd.conexion.execute(
                    "INSERT INTO entrega_notificacion (notificacion_id, entregado_en) "
                    "VALUES (?, ?)",
                    (notificacion_id, ts),
                )
            self._bd.conexion.commit()
        return notificacion_id

    def pendientes(self, transportista_id: int) -> list[Notificacion]:
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_NOTIFICACION} FROM notificacion "
                "WHERE transportista_id = ? AND entregado = 0 ORDER BY id",
                (transportista_id,),
            ).fetchall()
        return [_notificacion_de_fila(fila) for fila in filas]

    def buscar_por_id(self, notificacion_id: int) -> Notificacion | None:
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_NOTIFICACION} FROM notificacion WHERE id = ?",
                (notificacion_id,),
            ).fetchone()
        return _notificacion_de_fila(fila) if fila is not None else None

    def por_entregar(self, max_reintentos: int, limite: int) -> list[int]:
        """Ids pendientes de transportistas vinculados, posteriores a su vínculo (§15.4).

        Un aviso anterior al vínculo no se envía: el transportista aún no tenía
        cuenta de mensajería [DEC, docs/mensajeria.md]. Tampoco los que ya
        agotaron sus reintentos por un error permanente (chat bloqueado).
        """
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT notificacion.id FROM notificacion "
                "JOIN vinculo_mensajeria "
                "ON vinculo_mensajeria.transportista_id = notificacion.transportista_id "
                "LEFT JOIN entrega_notificacion "
                "ON entrega_notificacion.notificacion_id = notificacion.id "
                "WHERE notificacion.entregado = 0 "
                "AND notificacion.ts >= vinculo_mensajeria.vinculado_en "
                "AND COALESCE(entrega_notificacion.reintentos, 0) < ? "
                "ORDER BY notificacion.id LIMIT ?",
                (max_reintentos, limite),
            ).fetchall()
        return [int(fila[0]) for fila in filas]

    def marcar_entregada(self, notificacion_id: int, ts: str) -> None:
        """Deja el aviso ``entregado`` con su instante de entrega (§15.4)."""
        with self._bd.candado:
            self._bd.conexion.execute(
                "UPDATE notificacion SET entregado = 1 WHERE id = ?", (notificacion_id,)
            )
            self._bd.conexion.execute(
                "INSERT INTO entrega_notificacion (notificacion_id, entregado_en) VALUES (?, ?) "
                "ON CONFLICT (notificacion_id) DO UPDATE SET entregado_en = excluded.entregado_en",
                (notificacion_id, ts),
            )
            self._bd.conexion.commit()

    def registrar_fallo(self, notificacion_id: int, error: str, cuenta_reintento: bool) -> None:
        """Guarda el último error; ``cuenta_reintento`` solo en fallos permanentes.

        Una caída de red no consume reintentos: el aviso debe salir cuando la
        conexión vuelva, tarde lo que tarde (§15.4 «sin internet, quedan
        pendientes»).
        """
        incremento = 1 if cuenta_reintento else 0
        with self._bd.candado:
            self._bd.conexion.execute(
                "INSERT INTO entrega_notificacion (notificacion_id, reintentos, ultimo_error) "
                "VALUES (?, ?, ?) ON CONFLICT (notificacion_id) DO UPDATE SET "
                "reintentos = reintentos + excluded.reintentos, "
                "ultimo_error = excluded.ultimo_error",
                (notificacion_id, incremento, error),
            )
            self._bd.conexion.commit()


def _notificacion_de_fila(fila: sqlite3.Row) -> Notificacion:
    return Notificacion(
        id=int(fila[0]),
        transportista_id=int(fila[1]),
        tipo=str(fila[2]),
        payload=cast(dict[str, object], json.loads(str(fila[3]))),
        ts=str(fila[4]),
        entregado=bool(fila[5]),
    )
