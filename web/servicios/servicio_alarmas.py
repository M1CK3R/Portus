"""Alarmas del servidor en la interfaz TERMINAL (SPECS §13.3, §6.3, Etapa 6).

Reconocimiento (una a una para críticas/altas; en lote para bajas/medias), la
lista de activas e históricas con filtro por severidad, y el comando
``AlarmaSilenciar`` (comando 13) que silencia la señal sonora **sin**
reconocer la alarma (§13.4: son acciones independientes).
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.alarma import Alarma
from web.repositorios.repositorio_alarmas import RepositorioAlarmas
from web.servicios.puertos import PublicadorLogica
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

CMD_ALARMA_SILENCIAR = "AlarmaSilenciar"


class ServicioAlarmas:
    """Reconocimiento y listado de alarmas para la pestaña Alarmas (§13.3)."""

    def __init__(
        self,
        alarmas: RepositorioAlarmas,
        publicador: PublicadorLogica,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._alarmas = alarmas
        self._publicador = publicador
        self._fabrica_instante = fabrica_instante

    def activas(self, severidad: str | None = None) -> list[Alarma]:
        """Lista de alarmas activas; ``severidad`` filtra (§13.3)."""
        return self._alarmas.activas(severidad=severidad)

    def historicas(self, severidad: str | None = None) -> list[Alarma]:
        return self._alarmas.historicas(severidad=severidad)

    def reconocer(self, alarma_id: int, usuario_id: int, comentario: str | None = None) -> bool:
        """Pasa una alarma activa a reconocida (§13.2); False si no estaba activa."""
        ts = marca_utc(self._fabrica_instante())
        return self._alarmas.reconocer(alarma_id, usuario_id, comentario, ts)

    def reconocer_todas_baja_media(self, usuario_id: int) -> int:
        """Reconoce en lote las de severidad BAJA y MEDIA (§13.3).

        Las CRITICA y ALTA se reconocen una por una; esta operación las excluye.
        """
        ts = marca_utc(self._fabrica_instante())
        cantidad = self._alarmas.reconocer_todas_baja_media(usuario_id, ts)
        REGISTRO.info(
            "Reconocidas %d alarmas (baja/media) en lote por el usuario %d", cantidad, usuario_id
        )
        return cantidad

    def silenciar(self, usuario: str) -> str:
        """Silencia la señal sonora sin reconocer la alarma (§13.4, comando 13).

        ``AlarmaSilenciar`` nunca se rechaza (§6.1); el controlador acalla la
        sirena pero las alarmas siguen activas hasta su reconocimiento.
        """
        cmd_id = self._publicador.publicar_comando(CMD_ALARMA_SILENCIAR, {}, usuario)
        REGISTRO.info("AlarmaSilenciar enviado por %s (cmd_id=%s)", usuario, cmd_id)
        return cmd_id
