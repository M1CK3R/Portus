"""Cliente MQTT del carril Aplicación: consumidor de eventos y salida de publicaciones.

Se suscribe a ``portus/#`` (SPECS §5.1) y alimenta :class:`NucleoLogica` en
su propio hilo de red, sin bloquear a waitress (PY-4). Implementa a la vez el
contrato ``SalidaBroker`` para que el publicador de la lógica use el mismo
cliente. La conexión es tolerante: si el broker no está disponible al
arrancar, el servicio web sigue operando (sin lógica de turno en vivo) y el
reintento de paho lo reconecta cuando aparezca.
"""

import logging

import paho.mqtt.client as mqtt
from paho.mqtt.client import Client, MQTTMessage
from paho.mqtt.enums import CallbackAPIVersion

from web.servicios.nucleo_logica import NucleoLogica

REGISTRO = logging.getLogger(__name__)

QOS_SUSCRIPCION = 1


class ClienteLogica:
    """Cliente paho único del proceso portus-web: consume y publica (PY-7)."""

    def __init__(self, host: str, puerto: int, usuario: str, contrasena: str) -> None:
        self._host = host
        self._puerto = puerto
        self._usuario = usuario
        self._contrasena = contrasena
        self._nucleo: NucleoLogica | None = None
        self._cliente: mqtt.Client | None = None

    def vincular(self, nucleo: NucleoLogica) -> None:
        """Asigna el núcleo que atiende los mensajes recibidos (dueño único, PY-7)."""
        self._nucleo = nucleo

    def iniciar(self) -> None:
        """Conecta al broker y lanza el bucle de red en su hilo propio (PY-4, PY-6)."""
        cliente = Client(CallbackAPIVersion.VERSION2, client_id="portus-web-logica")
        cliente.username_pw_set(self._usuario, self._contrasena)
        cliente.on_connect = self._al_conectar
        cliente.on_message = self._al_mensaje
        cliente.on_disconnect = self._al_desconectar
        try:
            cliente.connect_async(self._host, self._puerto, keepalive=30)
        except OSError as error:
            # D-6: fallo registrado y visible; el servicio web continúa.
            REGISTRO.error(
                "No se pudo programar la conexión al broker %s:%d: %s",
                self._host,
                self._puerto,
                error,
            )
        cliente.loop_start()
        self._cliente = cliente
        REGISTRO.info("Consumidor MQTT de la lógica iniciado (%s:%d)", self._host, self._puerto)

    def detener(self) -> None:
        """Detiene el bucle de red y desconecta con limpieza (PY-6)."""
        if self._cliente is not None:
            self._cliente.loop_stop()
            self._cliente.disconnect()
            self._cliente = None

    # ------------------------------------------------- contrato SalidaBroker

    def publicar(self, topico: str, datos: str, qos: int, retain: bool) -> None:
        """Publica en el broker; sin cliente conectado se registra y se descarta (D-6)."""
        if self._cliente is None:
            REGISTRO.warning("Publicación descartada (cliente MQTT no iniciado): %s", topico)
            return
        self._cliente.publish(topico, datos, qos=qos, retain=retain)

    # -------------------------------------------------------------- callbacks

    def _al_conectar(
        self,
        cliente: Client,
        userdata: object,
        banderas: object,
        razon: object,
        propiedades: object | None = None,
    ) -> None:
        """Se suscribe a todo el espacio del proyecto; QoS 1 con dedup en el núcleo."""
        _ = (userdata, banderas, propiedades)
        resultado, _ = cliente.subscribe("portus/#", qos=QOS_SUSCRIPCION)
        if resultado == 0:
            REGISTRO.info("Suscripción portus/# activa")
        else:
            REGISTRO.error("La suscripción portus/# falló con código %s", resultado)

    def _al_mensaje(self, cliente: Client, userdata: object, mensaje: MQTTMessage) -> None:
        """Alimenta el núcleo; un evento que falla no detiene al consumidor (P-5)."""
        _ = (cliente, userdata)
        nucleo = self._nucleo
        if nucleo is None:
            return
        try:
            nucleo.atender_mensaje(mensaje.topic, mensaje.payload)
        except Exception:
            # P-5: un evento que falla no detiene al consumidor; queda registrado.
            REGISTRO.exception("Fallo procesando el mensaje de %s", mensaje.topic)

    def _al_desconectar(
        self,
        cliente: Client,
        userdata: object,
        banderas: object,
        razon: object,
        propiedades: object | None = None,
    ) -> None:
        """Registro de la desconexión; paho reintentará por su cuenta."""
        _ = (cliente, userdata, banderas, propiedades)
        REGISTRO.warning("Desconectado del broker (código %s); paho reintentará", razon)
