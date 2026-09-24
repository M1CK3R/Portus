"""Modelos del canal de mensajería, independientes de Telegram (CODESTYLE PY-2, I-4).

El adaptador convierte cada *update* de Telegram en :class:`MensajeEntrante`
o :class:`PulsacionBoton` (``chat_id`` → ``id_chat``, ``callback_data`` →
``dato``) y cada :class:`Respuesta` en un ``sendMessage``. La lógica del bot
solo conoce estos tipos, así se prueba sin red ni librería externa (T-5).
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class MensajeEntrante:
    """Texto que escribió el usuario en su chat privado con el bot."""

    id_chat: int
    texto: str


@dataclass(frozen=True)
class PulsacionBoton:
    """Botón en línea pulsado (``callback_data`` de Telegram, ≤ 64 bytes)."""

    id_chat: int
    dato: str


@dataclass(frozen=True)
class Boton:
    """Botón de un teclado en línea: texto visible y dato corto de retorno."""

    texto: str
    dato: str


@dataclass(frozen=True)
class Respuesta:
    """Lo que el bot contesta: texto plano y, opcionalmente, filas de botones."""

    texto: str
    botones: tuple[tuple[Boton, ...], ...] = field(default_factory=tuple)


class ErrorCanal(Exception):
    """Base de los fallos al enviar por el canal externo (§15.4)."""


class ErrorLimiteCanal(ErrorCanal):
    """El canal pidió esperar (Telegram 429 con ``retry_after``)."""

    def __init__(self, espera_s: float) -> None:
        super().__init__(f"límite de envío: esperar {espera_s:.0f} s")
        self.espera_s = espera_s


class ErrorRedCanal(ErrorCanal):
    """Sin conexión o tiempo agotado: el aviso queda pendiente sin gastar reintentos."""


class ErrorPermanenteCanal(ErrorCanal):
    """El canal rechazó el envío (chat bloqueado o inexistente): cuenta reintento."""


class CanalMensajeria(Protocol):
    """Contrato de salida hacia el canal externo; lo implementa el adaptador."""

    async def enviar(self, id_chat: int, texto: str) -> None:
        """Envía texto plano; eleva una subclase de :class:`ErrorCanal` si falla."""
        ...
