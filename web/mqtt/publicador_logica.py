"""Publicador MQTT de la lógica: envoltorio único, QoS 1, sin retain (SPECS §5.5).

Implementa el contrato ``PublicadorLogica`` de los servicios. Los mensajes
del servidor (autorizaciones, trabajos, cambios de turno, retenciones y
alarmas) salen con QoS 1 porque el tablero y el bot dependen de no perderlos;
ninguno usa retain salvo los que ya maneja el puente (estado del enlace).
"""

import logging
from collections.abc import Callable
from typing import Protocol

from web.mqtt.envoltorio import (
    ORIGEN_SERVIDOR,
    TIPO_COMANDO_SOLICITUD,
    TOPICO_CMD_SOLICITUD,
    MensajeServidor,
    identificador_nuevo,
    marca_utc,
    serializar_mensaje,
)

REGISTRO = logging.getLogger(__name__)

QOS_MENSAJES_SERVIDOR = 1


class SalidaBroker(Protocol):
    """Contrato mínimo hacia paho, inyectable en pruebas (T-5)."""

    def publicar(self, topico: str, datos: str, qos: int, retain: bool) -> None: ...


class PublicadorLogicaWeb:
    """Construye y publica el envoltorio §5.2 para los mensajes del servidor.

    Implementa el contrato completo ``PublicadorLogica``: ``publicar_comando``
    genera el ``cmd_id`` con la fábrica inyectada (D-8) y lo envía por
    ``portus/cmd/solicitud`` para que el puente lo convierta en trama CMD (§6.4).
    """

    def __init__(
        self,
        salida: SalidaBroker,
        fabrica_ts: Callable[[], str] = marca_utc,
        fabrica_cmd_id: Callable[[], str] | None = None,
    ) -> None:
        self._salida = salida
        self._fabrica_ts = fabrica_ts
        self._fabrica_cmd_id = fabrica_cmd_id or (lambda: identificador_nuevo())

    def publicar(self, topico: str, tipo: str, datos: dict[str, object]) -> None:
        """Publica un mensaje del servidor con id aleatorio y QoS 1 (§5.5)."""
        mensaje = MensajeServidor(
            id=identificador_nuevo(),
            ts=self._fabrica_ts(),
            origen=ORIGEN_SERVIDOR,
            tipo=tipo,
            seq=None,
            datos=datos,
        )
        self._salida.publicar(topico, serializar_mensaje(mensaje), QOS_MENSAJES_SERVIDOR, False)
        REGISTRO.debug("Publicado %s en %s", mensaje.id, topico)

    def publicar_comando(self, nombre: str, parametros: dict[str, str], usuario: str) -> str:
        """Envía una solicitud de comando con su cmd_id y devuelve el identificador."""
        cmd_id = self._fabrica_cmd_id()
        self.publicar(
            TOPICO_CMD_SOLICITUD,
            TIPO_COMANDO_SOLICITUD,
            {"cmd_id": cmd_id, "nombre": nombre, "parametros": parametros, "usuario": usuario},
        )
        return cmd_id


class PublicadorSordo:
    """Publicador nulo para modo sin broker y pruebas unitarias (T-5)."""

    def publicar(self, topico: str, tipo: str, datos: dict[str, object]) -> None:
        _ = (topico, tipo, datos)

    def publicar_comando(self, nombre: str, parametros: dict[str, str], usuario: str) -> str:
        _ = (nombre, parametros, usuario)
        return "sordo"
