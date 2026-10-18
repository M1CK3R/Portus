"""Publicación de mensajes MQTT con el envoltorio único del proyecto (SPECS §5.2, §5.5).

Decide QoS y retain según el tópico: QoS 0 y retain en el latido
``portus/evt/estado``; QoS 1 en el resto de eventos, comandos y respuestas;
el estado del enlace en ``portus/srv/enlace`` se publica con retain para que
un suscriptor nuevo conozca el último estado. El Last Will del puente es la
contraparte ``puente=caido`` del mismo tópico.
"""

import logging
import uuid
from typing import Protocol

from puente.gestor_comandos import RespuestaComando
from puente.mensajes_mqtt import (
    NAMESPACE_PORTUS,
    QOS_COMANDOS,
    QOS_EVENTOS,
    QOS_LATIDO,
    TIPO_EVENTO_ALARMA_SERVIDOR,
    TIPO_EVENTO_COMANDO_RESPUESTA,
    TIPO_EVENTO_ENLACE_ESTADO,
    TIPO_EVENTO_ENLACE_SALTO,
    TOPICO_POR_TIPO_EVENTO,
    MensajeMqtt,
    armar_mensaje,
    identificador_nuevo,
    identificador_respuesta_comando,
    marca_tiempo_utc,
    mensaje_de_trama,
    serializar_mensaje,
)
from puente.protocolo import TIPO_EST, Trama
from puente.secuencia import EventoSecuencia
from puente.vigilante_latido import EstadoEnlace

REGISTRO = logging.getLogger(__name__)


class SalidaMqtt(Protocol):
    """Contrato de salida hacia el broker, inyectable en pruebas (CODESTYLE T-5)."""

    def publicar(self, topico: str, datos: str, qos: int, retain: bool) -> None: ...


class PublicadorEventos:
    """Construye y publica el envoltorio JSON obligatorio en cada tópico."""

    def __init__(self, salida: SalidaMqtt) -> None:
        self._salida = salida

    @property
    def salida(self) -> SalidaMqtt:
        return self._salida

    def publicar_evento_controlador(self, trama: Trama) -> MensajeMqtt:
        """Publica un evento C→S; el latido sale con QoS 0 y retain (§5.5)."""
        mensaje = mensaje_de_trama(trama, marca_tiempo_utc())
        es_latido = trama.tipo == TIPO_EST
        qos = QOS_LATIDO if es_latido else QOS_EVENTOS
        self._publicar(mensaje, qos, retain=es_latido)
        return mensaje

    def publicar_respuesta_comando(self, respuesta: RespuestaComando) -> MensajeMqtt:
        """Publica la respuesta real del controlador o el NAK sintético (§6.4)."""
        datos: dict[str, object] = {
            "cmd_id": respuesta.cmd_id,
            "nombre": respuesta.nombre,
            "estado": respuesta.estado,
            "causa": respuesta.causa,
            "sintetica": respuesta.sintetica,
        }
        if respuesta.tardia:
            datos["tardia"] = True
        mensaje = armar_mensaje(
            id=identificador_respuesta_comando(
                respuesta.cmd_id or "", respuesta.estado, respuesta.causa
            ),
            ts=marca_tiempo_utc(),
            origen="puente" if respuesta.sintetica else "controlador",
            tipo=TIPO_EVENTO_COMANDO_RESPUESTA,
            seq=respuesta.seq,
            datos=datos,
        )
        self._publicar(mensaje, QOS_COMANDOS, retain=False)
        return mensaje

    def publicar_salto_secuencia(self, salto: EventoSecuencia) -> MensajeMqtt:
        """Publica el diagnóstico del salto de SEQ que dispara la solicitud SYN (§4.2)."""
        datos: dict[str, object] = {
            "seq_esperada": None if salto.seq_previa is None else salto.seq_previa + 1,
            "seq_recibida": salto.seq,
            "faltantes": salto.faltantes,
        }
        mensaje = armar_mensaje(
            id=identificador_nuevo(),
            ts=marca_tiempo_utc(),
            origen="puente",
            tipo=TIPO_EVENTO_ENLACE_SALTO,
            seq=salto.seq,
            datos=datos,
        )
        self._publicar(mensaje, QOS_EVENTOS, retain=False)
        return mensaje

    def publicar_alarma_enlace(self, datos_al01: dict[str, object]) -> MensajeMqtt:
        """Publica AL01 en portus/srv/alarma con origen servidor (SPECS §13.1)."""
        mensaje = armar_mensaje(
            id=identificador_nuevo(),
            ts=marca_tiempo_utc(),
            origen="servidor",
            tipo=TIPO_EVENTO_ALARMA_SERVIDOR,
            seq=None,
            datos=datos_al01,
        )
        self._publicar(mensaje, QOS_EVENTOS, retain=False)
        return mensaje

    def publicar_estado_enlace(
        self,
        estado: EstadoEnlace,
        ultimo_latido_ts: str | None,
        contadores: dict[str, int],
    ) -> MensajeMqtt:
        """Publica el estado del enlace con retain; alimenta el sinóptico (§14.1)."""
        datos: dict[str, object] = {
            "puente": "activo",
            "enlace": estado.value,
            "ultimo_latido_ts": ultimo_latido_ts,
            **contadores,
        }
        mensaje = armar_mensaje(
            id=identificador_nuevo(),
            ts=marca_tiempo_utc(),
            origen="puente",
            tipo=TIPO_EVENTO_ENLACE_ESTADO,
            seq=None,
            datos=datos,
        )
        self._publicar(mensaje, QOS_COMANDOS, retain=True)
        return mensaje

    def armar_ultimo_testamento(self) -> str:
        """Payload del Last Will: puente=caido con retain (SPECS §5.5)."""
        mensaje = armar_mensaje(
            id=identificador_ultimo_testamento(),
            ts=marca_tiempo_utc(),
            origen="puente",
            tipo=TIPO_EVENTO_ENLACE_ESTADO,
            seq=None,
            datos={"puente": "caido", "enlace": EstadoEnlace.PERDIDO.value},
        )
        return serializar_mensaje(mensaje)

    def _publicar(self, mensaje: MensajeMqtt, qos: int, retain: bool) -> None:
        topico = TOPICO_POR_TIPO_EVENTO[mensaje.tipo]
        self._salida.publicar(topico, serializar_mensaje(mensaje), qos, retain)
        REGISTRO.debug("Publicado %s en %s (qos=%d, retain=%s)", mensaje.id, topico, qos, retain)


def identificador_ultimo_testamento() -> str:
    """Id determinista del Last Will; el ts corresponde al momento de conexión."""
    return str(uuid.uuid5(NAMESPACE_PORTUS, "puente:caido"))
