"""Estado por chat del bot: conversación de ``/cita`` e intentos de vinculación.

``/cita`` es multipaso (SPECS §15.2 [PROP]): ``esperando_contenedor`` →
``esperando_franja``. El estado expira por inactividad y cualquier otro
comando lo cancela. Guarda qué opciones se ofrecieron para aceptar solo
botones de esa lista (S-2: un ``callback_data`` fabricado no sirve).

Vive en memoria del proceso: si portus-msg se reinicia, el transportista
vuelve a escribir ``/cita`` (la cita misma solo existe al confirmarse en BD).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

INACTIVIDAD_CONVERSACION_MIN = 10
"""Una conversación de /cita sin respuesta en este lapso se descarta."""
INTENTOS_VINCULACION_MAXIMOS = 5
VENTANA_INTENTOS_VINCULACION_MIN = 15
"""Tope de /vincular por chat: frena la prueba de códigos al azar (S-2)."""


class PasoCita(StrEnum):
    ESPERANDO_CONTENEDOR = "esperando_contenedor"
    ESPERANDO_FRANJA = "esperando_franja"


@dataclass(frozen=True)
class ConversacionCita:
    """Dónde va la solicitud de cita de un chat y qué se le ofreció."""

    paso: PasoCita
    transportista_id: int
    actualizada: datetime
    contenedores: dict[int, str] = field(default_factory=dict)
    """manifiesto_id → contenedor ofrecidos en el primer paso."""
    manifiesto_id: int | None = None
    contenedor_id: str = ""
    franjas: frozenset[tuple[str, str]] = frozenset()
    """(fecha, inicio) ofrecidas en el segundo paso."""


class RegistroConversaciones:
    """Conversaciones vigentes por ``id_chat`` con expiración (dueño único, PY-7)."""

    def __init__(
        self,
        fabrica_instante: Callable[[], datetime],
        inactividad: timedelta = timedelta(minutes=INACTIVIDAD_CONVERSACION_MIN),
    ) -> None:
        self._fabrica_instante = fabrica_instante
        self._inactividad = inactividad
        self._por_chat: dict[int, ConversacionCita] = {}

    def ahora(self) -> datetime:
        return self._fabrica_instante()

    def guardar(self, id_chat: int, conversacion: ConversacionCita) -> None:
        self._por_chat[id_chat] = conversacion

    def vigente(self, id_chat: int) -> ConversacionCita | None:
        """La conversación del chat si no expiró; la vencida se descarta."""
        conversacion = self._por_chat.get(id_chat)
        if conversacion is None:
            return None
        if self._fabrica_instante() - conversacion.actualizada > self._inactividad:
            del self._por_chat[id_chat]
            return None
        return conversacion

    def cancelar(self, id_chat: int) -> None:
        self._por_chat.pop(id_chat, None)


class LimitadorVinculacion:
    """Cuenta los ``/vincular`` de cada chat en una ventana deslizante."""

    def __init__(
        self,
        fabrica_instante: Callable[[], datetime],
        maximo: int = INTENTOS_VINCULACION_MAXIMOS,
        ventana: timedelta = timedelta(minutes=VENTANA_INTENTOS_VINCULACION_MIN),
    ) -> None:
        self._fabrica_instante = fabrica_instante
        self._maximo = maximo
        self._ventana = ventana
        self._intentos: dict[int, list[datetime]] = {}

    def permitir(self, id_chat: int) -> bool:
        """Registra el intento; False si el chat ya agotó los de la ventana."""
        ahora = self._fabrica_instante()
        recientes = [t for t in self._intentos.get(id_chat, []) if ahora - t < self._ventana]
        if len(recientes) >= self._maximo:
            self._intentos[id_chat] = recientes
            return False
        recientes.append(ahora)
        self._intentos[id_chat] = recientes
        return True
