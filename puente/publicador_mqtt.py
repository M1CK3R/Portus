"""Cliente MQTT del puente sobre paho-mqtt (SPECS §5.5).

Configura el Last Will en ``portus/srv/enlace`` con ``puente=caido``, se
suscribe a todo el espacio de tópicos (``TOPICO_COMODIN``) para recibir los
comandos de la plataforma y entregar cada mensaje al manejador que inyecta
el orquestador. Toda la lógica de publicación (envoltorio, QoS y retain)
vive en ``PublicadorEventos``; esta clase es solo la frontera con paho.
"""

import logging
from collections.abc import Callable

from paho.mqtt.client import (
    MQTT_ERR_SUCCESS,
    Client,
    ConnectFlags,
    DisconnectFlags,
    MQTTMessage,
    MQTTv311,
)
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from puente.mensajes_mqtt import QOS_COMANDOS, TOPICO_COMODIN, TOPICO_SRV_ENLACE

REGISTRO = logging.getLogger(__name__)

ManejadorMensaje = Callable[[str, bytes], None]

QOS_SUSCRIPCION = 1
RETRASO_RECONEXION_S = 3


class PublicadorPaho:
    """Frontera con el broker: conexión, suscripción, Last Will y recepción."""

    def __init__(
        self,
        host: str,
        puerto: int,
        usuario: str,
        contrasena: str,
        id_cliente: str,
        mensaje_ultimo_testamento: str,
        manejador: ManejadorMensaje,
        al_publicar_activo: Callable[[], None],
    ) -> None:
        self._host = host
        self._puerto = puerto
        self._manejador = manejador
        self._al_publicar_activo = al_publicar_activo
        self._cliente = Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=id_cliente,
            protocol=MQTTv311,
        )
        self._cliente.username_pw_set(usuario, contrasena)
        self._cliente.will_set(
            TOPICO_SRV_ENLACE,
            mensaje_ultimo_testamento.encode("utf-8"),
            qos=QOS_COMANDOS,
            retain=True,
        )
        self._cliente.on_connect = self._al_conectar
        self._cliente.on_message = self._al_llegar_mensaje
        self._cliente.on_disconnect = self._al_desconectar

    def conectar(self) -> None:
        self._cliente.connect(self._host, self._puerto, keepalive=30)

    def iniciar_bucle(self) -> None:
        """Inicia el hilo de red de paho; los callbacks llegan en ese hilo."""
        self._cliente.loop_start()

    def desconectar(self) -> None:
        self._cliente.loop_stop()
        self._cliente.disconnect()

    def publicar(self, topico: str, datos: str, qos: int, retain: bool) -> None:
        informacion = self._cliente.publish(topico, datos, qos=qos, retain=retain)
        if informacion.rc != MQTT_ERR_SUCCESS:
            REGISTRO.error("Publicación rechazada por paho (rc=%s) en %s", informacion.rc, topico)

    def _al_conectar(
        self,
        cliente: Client,
        datos_usuario: None,
        banderas: ConnectFlags,
        codigo: ReasonCode,
        propiedades: Properties | None,
    ) -> None:
        if not codigo.is_failure:
            REGISTRO.info("Conectado al broker MQTT (rc=%s)", codigo)
            cliente.subscribe(TOPICO_COMODIN, qos=QOS_SUSCRIPCION)
            self._al_publicar_activo()
        else:
            REGISTRO.error("Fallo de conexión con el broker MQTT (rc=%s)", codigo)

    def _al_llegar_mensaje(
        self, cliente: Client, datos_usuario: None, mensaje: MQTTMessage
    ) -> None:
        self._manejador(mensaje.topic, mensaje.payload)

    def _al_desconectar(
        self,
        cliente: Client,
        datos_usuario: None,
        banderas: DisconnectFlags,
        codigo: ReasonCode,
        propiedades: Properties | None,
    ) -> None:
        REGISTRO.warning("Desconectado del broker MQTT (rc=%s)", codigo)
