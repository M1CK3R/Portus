"""Escucha MQTT de los avisos ``portus/srv/*`` (SPECS §5.3, §15.4; CODESTYLE PY-4, P-4, P-5).

Corre en el hilo de red de paho, separado del bucle asyncio del bot. Cada
mensaje ``notificacion.<tipo>`` trae el id de la fila persistida; el id se
entrega por ``al_aviso`` (que el arranque conecta con
``loop.call_soon_threadsafe``) y el despachador relee la fila. Los mensajes
repetidos por QoS 1 se descartan por el ``id`` del envoltorio (P-4); los mal
formados se registran y se descartan (P-5).
"""

import json
import logging
from collections import OrderedDict
from collections.abc import Callable

from paho.mqtt.client import Client, MQTTMessage
from paho.mqtt.enums import CallbackAPIVersion

from web.modelos.notificacion import PREFIJO_TIPO_MQTT
from web.mqtt.envoltorio import topico

REGISTRO = logging.getLogger(__name__)

TOPICOS_DE_AVISOS: tuple[str, ...] = (
    topico("srv", "turno"),
    topico("srv", "retencion"),
    topico("srv", "cita"),
)
"""Los tópicos de los que salen notificaciones (acl_portus: ``portus-msg`` solo lee)."""
QOS_SUSCRIPCION = 1
KEEPALIVE_S = 30
IDS_RECORDADOS = 2000
"""Ventana de deduplicación por id del envoltorio; sobra para los reenvíos de QoS 1."""


def id_de_aviso(carga: bytes) -> tuple[str, int] | None:
    """(id del envoltorio, id de la notificación) si el mensaje es un aviso válido."""
    try:
        envoltorio = json.loads(carga.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(envoltorio, dict):
        return None
    id_mensaje, tipo, datos = envoltorio.get("id"), envoltorio.get("tipo"), envoltorio.get("datos")
    if not (isinstance(id_mensaje, str) and isinstance(tipo, str) and isinstance(datos, dict)):
        return None
    if not tipo.startswith(PREFIJO_TIPO_MQTT):
        return None
    notificacion_id = datos.get("notificacion")
    if isinstance(notificacion_id, bool) or not isinstance(notificacion_id, int):
        return None
    return (id_mensaje, notificacion_id)


class EscuchaAvisos:
    """Cliente paho de portus-msg: solo suscribe, nunca publica (S-4)."""

    def __init__(
        self,
        host: str,
        puerto: int,
        usuario: str,
        contrasena: str,
        al_aviso: Callable[[int], None],
    ) -> None:
        self._host = host
        self._puerto = puerto
        self._usuario = usuario
        self._contrasena = contrasena
        self._al_aviso = al_aviso
        self._vistos: OrderedDict[str, None] = OrderedDict()
        self._cliente: Client | None = None

    def iniciar(self) -> None:
        """Conecta en segundo plano; paho reintenta solo si el broker no está (PY-4)."""
        cliente = Client(CallbackAPIVersion.VERSION2, client_id="portus-msg")
        cliente.username_pw_set(self._usuario, self._contrasena)
        cliente.on_connect = self._al_conectar
        cliente.on_message = self._al_mensaje
        cliente.on_disconnect = self._al_desconectar
        try:
            cliente.connect_async(self._host, self._puerto, keepalive=KEEPALIVE_S)
        except OSError as error:
            REGISTRO.error("No se pudo programar la conexión al broker: %s", error)
        cliente.loop_start()
        self._cliente = cliente
        REGISTRO.info("Escucha de avisos MQTT iniciada (%s:%d)", self._host, self._puerto)

    def detener(self) -> None:
        if self._cliente is not None:
            self._cliente.loop_stop()
            self._cliente.disconnect()
            self._cliente = None

    def atender(self, carga: bytes) -> bool:
        """Procesa una carga; True si entregó un aviso nuevo (lo usan las pruebas)."""
        aviso = id_de_aviso(carga)
        if aviso is None:
            return False
        id_mensaje, notificacion_id = aviso
        if id_mensaje in self._vistos:
            return False
        self._vistos[id_mensaje] = None
        if len(self._vistos) > IDS_RECORDADOS:
            self._vistos.popitem(last=False)
        self._al_aviso(notificacion_id)
        return True

    def _al_conectar(
        self,
        cliente: Client,
        userdata: object,
        banderas: object,
        razon: object,
        propiedades: object | None = None,
    ) -> None:
        _ = (userdata, banderas, propiedades)
        if getattr(razon, "is_failure", False):
            REGISTRO.error("El broker rechazó la conexión de portus-msg: %s", razon)
            return
        for topico_aviso in TOPICOS_DE_AVISOS:
            cliente.subscribe(topico_aviso, qos=QOS_SUSCRIPCION)
        REGISTRO.info("Suscrito a %s", ", ".join(TOPICOS_DE_AVISOS))

    def _al_mensaje(self, cliente: Client, userdata: object, mensaje: MQTTMessage) -> None:
        _ = (cliente, userdata)
        try:
            self.atender(mensaje.payload)
        except Exception:
            REGISTRO.exception("Fallo atendiendo el mensaje de %s", mensaje.topic)

    def _al_desconectar(
        self,
        cliente: Client,
        userdata: object,
        banderas: object,
        razon: object,
        propiedades: object | None = None,
    ) -> None:
        _ = (cliente, userdata, banderas, propiedades)
        REGISTRO.warning("portus-msg desconectado del broker (%s); paho reintentará", razon)
