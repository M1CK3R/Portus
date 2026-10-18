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
        """Ids de transportistas con cuenta de mensajería asociada (§15.1, §15.4)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT transportista_id FROM vinculo_mensajeria"
            ).fetchall()
        return {int(fila[0]) for fila in filas}

    # ------------------------------------------------ Etapa 10: vínculo del chat

    def consumir_y_vincular(self, codigo: str, id_chat: int, instante: str) -> int | None:
        """Consume el código y asocia el chat a su transportista en una transacción.

        El ``UPDATE ... WHERE usado_en IS NULL AND expira_en > ?`` es la
        garantía de un solo uso: si dos chats envían el mismo código a la vez,
        solo uno ve ``rowcount == 1`` (§15.1). El chat y el transportista
        pierden cualquier vínculo previo: una cuenta ↔ un transportista.
        Devuelve el id del transportista o None si el código ya no sirve.
        """
        with self._bd.candado:
            conexion = self._bd.conexion
            conexion.execute("BEGIN IMMEDIATE")
            try:
                cursor = conexion.execute(
                    "UPDATE codigo_vinculacion SET usado_en = ? "
                    "WHERE codigo = ? AND usado_en IS NULL AND expira_en > ?",
                    (instante, codigo, instante),
                )
                if cursor.rowcount != 1:
                    conexion.rollback()
                    return None
                fila = conexion.execute(
                    "SELECT transportista_id FROM codigo_vinculacion WHERE codigo = ?", (codigo,)
                ).fetchone()
                transportista_id = int(fila[0])
                conexion.execute(
                    "DELETE FROM vinculo_mensajeria "
                    "WHERE telegram_chat_id = ? OR transportista_id = ?",
                    (id_chat, transportista_id),
                )
                conexion.execute(
                    "INSERT INTO vinculo_mensajeria "
                    "(transportista_id, telegram_chat_id, vinculado_en) VALUES (?, ?, ?)",
                    (transportista_id, id_chat, instante),
                )
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise
        return transportista_id

    def transportista_de_chat(self, id_chat: int) -> int | None:
        """Transportista ligado al chat; None si el chat no está vinculado (§15.1 regla 5)."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT transportista_id FROM vinculo_mensajeria WHERE telegram_chat_id = ?",
                (id_chat,),
            ).fetchone()
        return int(fila[0]) if fila is not None else None

    def chat_de_transportista(self, transportista_id: int) -> int | None:
        """Chat al que se envían los avisos del transportista (§15.3); None sin vínculo."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT telegram_chat_id FROM vinculo_mensajeria WHERE transportista_id = ?",
                (transportista_id,),
            ).fetchone()
        return int(fila[0]) if fila is not None else None


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
