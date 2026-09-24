"""Repositorio de solicitudes de levante (SPECS §9.1, §9.4, §17.1, Etapa 7).

En la Etapa 5 solo se lee el estado del levante para la validación de garita;
la Etapa 7 agrega el ciclo completo: el AGENTE solicita, la AUTORIDAD otorga o
retiene, y el seguimiento del agente.
"""

import sqlite3
from dataclasses import dataclass

from web.repositorios.conexion_bd import ConexionBd, id_insertado

COLUMNAS_LEVANTE = (
    "id, manifiesto_id, agente_id, autoridad_id, estado, canal, motivo, solicitada_en, resuelta_en"
)

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
    agente_id: int | None = None
    autoridad_id: int | None = None
    solicitada_en: str | None = None
    resuelta_en: str | None = None


class RepositorioLevantes:
    """Consulta del levante para el paso 3 de la validación (§9.4) + Etapa 7."""

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

    def buscar_por_id(self, levante_id: int) -> Levante | None:
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_LEVANTE} FROM solicitud_levante WHERE id = ?",
                (levante_id,),
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

    def solicitar(self, manifiesto_id: int, agente_id: int, ts: str) -> int:
        """El AGENTE solicita el levante (§9.1); nace en estado ``solicitada``.

        Si ya existe la fila en ``sin_solicitud`` (semilla), se promueve en vez
        de insertar: ``ix_levante_por_manifiesto`` admite una sola por manifiesto.
        """
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "INSERT INTO solicitud_levante (manifiesto_id, agente_id, estado, solicitada_en) "
                "VALUES (?, ?, 'solicitada', ?) "
                "ON CONFLICT (manifiesto_id) DO UPDATE SET estado = 'solicitada', "
                "agente_id = excluded.agente_id, solicitada_en = excluded.solicitada_en, "
                "canal = NULL, motivo = NULL, autoridad_id = NULL, resuelta_en = NULL "
                "WHERE solicitud_levante.estado = 'sin_solicitud' "
                "RETURNING id",
                (manifiesto_id, agente_id, ts),
            ).fetchone()
            self._bd.conexion.commit()
        if fila is None:
            raise ValueError(f"el manifiesto {manifiesto_id} ya tiene levante en curso")
        return int(fila[0])

    def listar_pendientes(self) -> list[Levante]:
        """Solicitudes en ``solicitada`` para la bandeja de la AUTORIDAD (§14.9)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_LEVANTE} FROM solicitud_levante "
                "WHERE estado = 'solicitada' ORDER BY id"
            ).fetchall()
        return [_levante_de_fila(fila) for fila in filas]

    def otorgar(self, levante_id: int, canal: str, autoridad_id: int, ts: str) -> bool:
        """La AUTORIDAD otorga el levante con canal verde/rojo (§9.1, §9.2)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE solicitud_levante SET estado = 'otorgada', canal = ?, "
                "autoridad_id = ?, resuelta_en = ? WHERE id = ? AND estado = 'solicitada'",
                (canal, autoridad_id, ts, levante_id),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def retener(self, levante_id: int, motivo: str, autoridad_id: int, ts: str) -> bool:
        """La AUTORIDAD retiene el levante con motivo (§9.1, §9.2)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE solicitud_levante SET estado = 'retenida', motivo = ?, "
                "autoridad_id = ?, resuelta_en = ? WHERE id = ? AND estado = 'solicitada'",
                (motivo, autoridad_id, ts, levante_id),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def seguimiento_de_agente(self, agente_id: int) -> list[Levante]:
        """Solicitudes del agente para la pestaña Seguimiento (§14.8)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_LEVANTE} FROM solicitud_levante "
                "WHERE agente_id = ? ORDER BY id DESC",
                (agente_id,),
            ).fetchall()
        return [_levante_de_fila(fila) for fila in filas]


def _levante_de_fila(fila: sqlite3.Row) -> Levante:
    # COLUMNAS_LEVANTE: id, manifiesto_id, agente_id, autoridad_id, estado,
    # canal, motivo, solicitada_en, resuelta_en
    canal = fila[5]
    motivo = fila[6]
    agente = fila[2]
    autoridad = fila[3]
    return Levante(
        id=int(fila[0]),
        manifiesto_id=int(fila[1]),
        estado=str(fila[4]),
        canal=None if canal is None else str(canal),
        motivo=None if motivo is None else str(motivo),
        agente_id=None if agente is None else int(agente),
        autoridad_id=None if autoridad is None else int(autoridad),
        solicitada_en=None if fila[7] is None else str(fila[7]),
        resuelta_en=None if fila[8] is None else str(fila[8]),
    )
