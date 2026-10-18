"""Alta de las notificaciones al transportista (SPECS §15.3, §15.4; Etapa 10).

Único camino para crear un aviso: lo persiste en ``notificacion`` (fuente de
verdad, sobrevive a una caída del bot o de internet) y lo publica como
``notificacion.<tipo>`` en ``portus/srv/*`` con el id de la fila. El bot
(``mensajeria/``) escucha esos tópicos, lee la fila por su id y la entrega
por Telegram solo al transportista propietario (§15.3).
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.notificacion import TipoNotificacion, tipo_mqtt
from web.repositorios.repositorio_notificaciones import RepositorioNotificaciones
from web.servicios.puertos import PublicadorLogica
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)


class Notificador:
    """Persiste y anuncia los avisos automáticos del transportista (§15.3)."""

    def __init__(
        self,
        notificaciones: RepositorioNotificaciones,
        publicador: PublicadorLogica,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._notificaciones = notificaciones
        self._publicador = publicador
        self._fabrica_instante = fabrica_instante

    def notificar(
        self,
        topico: str,
        transportista_id: int,
        tipo: TipoNotificacion,
        payload: dict[str, object],
    ) -> int:
        """Guarda el aviso y lo publica; devuelve el id de la notificación."""
        notificacion_id = self._notificaciones.crear(
            transportista_id, tipo.value, payload, marca_utc(self._fabrica_instante())
        )
        self._publicador.publicar(
            topico,
            tipo_mqtt(tipo),
            {**payload, "notificacion": notificacion_id, "transportista": transportista_id},
        )
        REGISTRO.info(
            "Notificación %d (%s) al transportista %d",
            notificacion_id,
            tipo.value,
            transportista_id,
        )
        return notificacion_id
