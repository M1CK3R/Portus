"""Orquestador del puente: hilos, reconexión del serial y apagado limpio (CODESTYLE PY-4).

Hilos independientes sin bloqueo cruzado:

* ``hilo_lector``: lee el puerto serie y alimenta el núcleo; reconecta con
  retroceso fijo ante fallos del puerto.
* ``hilo_temporizadores``: expira comandos a los 2 s (§4.5), evalúa el
  vigilante cada segundo (§5.4) y reporta el estado del enlace (§5.7).
* ``hilo_ping``: emite PING hacia el controlador (§3.4, A13).
* El bucle de red de paho-mqtt corre en su propio hilo (publicador_mqtt).

Un fallo fatal en un hilo apaga el servicio con CRITICAL: systemd lo reinicia
(SPECS §19.2, Restart=always).
"""

import logging
import threading
import time
from collections.abc import Callable

from puente.configuracion import ConfiguracionPuente
from puente.enlace_serie import EnlaceSerie
from puente.gestor_comandos import GestorComandos
from puente.nucleo_puente import NucleoPuente
from puente.persistencia_sqlite import PersistenciaSqlite
from puente.protocolo import ContadorSecuenciaServidor
from puente.publicador_eventos import PublicadorEventos
from puente.publicador_mqtt import PublicadorPaho
from puente.secuencia import EmisorTramasServidor
from puente.tiempo import reloj_monotonico_ms
from puente.vigilante_latido import VigilanteLatido

REGISTRO = logging.getLogger(__name__)

TICK_TEMPORIZADORES_S = 0.2
TICKS_POR_SEGUNDO = 5
PERIODO_REPORTE_ENLACE_S = 30.0
RETARDO_RECONEXION_S = 2.0
SEGUNDOS_ENTRE_CICLOS_PRINCIPAL = 0.5
PAUSA_LECTURA_SIN_DATOS_S = 0.01


class SalidaBroker:
    """Adaptador SalidaMqtt que delega en paho cuando el broker está cableado."""

    def __init__(self) -> None:
        self._publicador: PublicadorPaho | None = None

    def asignar(self, publicador: PublicadorPaho) -> None:
        self._publicador = publicador

    def publicar(self, topico: str, datos: str, qos: int, retain: bool) -> None:
        if self._publicador is None:
            REGISTRO.debug("Publicación descartada (broker no conectado): %s", topico)
            return
        self._publicador.publicar(topico, datos, qos, retain)


class Puente:
    """Dueño de los recursos y de los hilos del servicio portus-puente."""

    def __init__(self, configuracion: ConfiguracionPuente) -> None:
        self._configuracion = configuracion
        self._activo = threading.Event()
        self._apagado = False
        self._hilo_lector: threading.Thread | None = None
        self._hilo_temporizadores: threading.Thread | None = None
        self._hilo_ping: threading.Thread | None = None
        self._puerto = EnlaceSerie(configuracion.ruta_puerto_serie, configuracion.baudios)
        self._persistencia = PersistenciaSqlite(configuracion.ruta_bd)
        arranque_ms = reloj_monotonico_ms()
        self._vigilante = VigilanteLatido(
            umbral_ms=configuracion.umbral_latido_ms, arranque_ms=arranque_ms
        )
        self._emisor = EmisorTramasServidor(ContadorSecuenciaServidor())
        self._gestor = GestorComandos(
            self._emisor, tiempo_limite_s=configuracion.tiempo_limite_comando_s
        )
        self._salida_broker = SalidaBroker()
        self._publicador_eventos = PublicadorEventos(salida=self._salida_broker)
        self._nucleo = NucleoPuente(
            puerto=self._puerto,
            publicador=self._publicador_eventos,
            gestor=self._gestor,
            emisor=self._emisor,
            vigilante=self._vigilante,
            persistencia=self._persistencia,
            reloj_ms=reloj_monotonico_ms,
        )
        self._publicador_broker: PublicadorPaho | None = None

    # ------------------------------------------------------------------- ciclo

    def ejecutar(self) -> None:
        """Arranca broker, serial y hilos; bloquea hasta la señal de apagado."""
        self._activo.set()
        self._publicador_broker = PublicadorPaho(
            host=self._configuracion.mqtt_host,
            puerto=self._configuracion.mqtt_puerto,
            usuario=self._configuracion.mqtt_usuario,
            contrasena=self._configuracion.mqtt_contrasena,
            id_cliente="portus-puente",
            mensaje_ultimo_testamento=self._publicador_eventos.armar_ultimo_testamento(),
            manejador=self._nucleo.atender_mensaje_mqtt,
            al_publicar_activo=self._nucleo.publicar_estado_enlace,
        )
        self._salida_broker.asignar(self._publicador_broker)
        try:
            self._publicador_broker.conectar()
        except OSError as error:
            REGISTRO.error("No se pudo conectar al broker MQTT: %s", error)
        self._publicador_broker.iniciar_bucle()
        self._abrir_serial_con_reintento()
        self._nucleo.alarma_retroactiva_si_aplica()
        self._nucleo.volcar_estado_inicial()
        self._hilo_lector = threading.Thread(
            target=self._bucle_protegido, args=(self._ciclo_lector, "lector"), daemon=True
        )
        self._hilo_temporizadores = threading.Thread(
            target=self._bucle_protegido,
            args=(self._ciclo_temporizadores, "temporizadores"),
            daemon=True,
        )
        self._hilo_ping = threading.Thread(
            target=self._bucle_protegido, args=(self._ciclo_ping, "ping"), daemon=True
        )
        self._hilo_lector.start()
        self._hilo_temporizadores.start()
        self._hilo_ping.start()
        REGISTRO.info("Puente PORTUS en operación")
        while self._activo.is_set():
            time.sleep(SEGUNDOS_ENTRE_CICLOS_PRINCIPAL)
        self.apagar()

    def detener(self) -> None:
        self._activo.clear()

    def apagar(self) -> None:
        """Cierra recursos en orden inverso; es idempotente (CODESTYLE PY-6)."""
        if not self._activo.is_set() and self._apagado:
            return
        self._apagado = True
        REGISTRO.info("Apagando el puente...")
        self._activo.clear()
        if self._publicador_broker is not None:
            self._publicador_broker.desconectar()
        if self._puerto.esta_abierto:
            self._puerto.cerrar()
        self._persistencia.cerrar()
        REGISTRO.info("Puente apagado")

    # -------------------------------------------------------------------- hilos

    def _bucle_protegido(self, ciclo: Callable[[], None], nombre: str) -> None:
        """Ejecuta un ciclo de hilo; un fallo fatal apaga el servicio (D-3, D-6)."""
        try:
            ciclo()
        except Exception:
            REGISTRO.critical(
                "Fallo fatal en el hilo %s; se detiene el puente para reinicio del servicio",
                nombre,
                exc_info=True,
            )
            self.detener()

    def _ciclo_lector(self) -> None:
        while self._activo.is_set():
            if not self._puerto.esta_abierto:
                if not self._intentar_reabrir_serial():
                    continue
            try:
                datos = self._puerto.leer_disponible()
            except OSError as error:
                REGISTRO.error("Fallo de lectura serial: %s; se reabre el puerto", error)
                self._puerto.cerrar()
                continue
            if datos:
                self._nucleo.procesar_bytes(datos)
            else:
                time.sleep(PAUSA_LECTURA_SIN_DATOS_S)

    def _ciclo_temporizadores(self) -> None:
        ticks = 0
        while self._activo.is_set():
            time.sleep(TICK_TEMPORIZADORES_S)
            ticks += 1
            self._nucleo.expirar_comandos()
            if ticks % TICKS_POR_SEGUNDO == 0:
                self._nucleo.comprobar_vigilante()
            if ticks * TICK_TEMPORIZADORES_S >= PERIODO_REPORTE_ENLACE_S:
                ticks = 0
                self._nucleo.publicar_estado_enlace()

    def _ciclo_ping(self) -> None:
        while self._activo.is_set():
            time.sleep(self._configuracion.periodo_ping_s)
            if self._puerto.esta_abierto:
                try:
                    self._nucleo.emitir_ping()
                except OSError as error:
                    REGISTRO.error("Fallo al enviar PING: %s", error)

    # ------------------------------------------------------------------- serial

    def _abrir_serial_con_reintento(self) -> None:
        while self._activo.is_set():
            try:
                self._puerto.abrir()
                return
            except (OSError, ValueError) as error:
                REGISTRO.error(
                    "No se pudo abrir %s: %s; nuevo intento en %.0f s",
                    self._configuracion.ruta_puerto_serie,
                    error,
                    RETARDO_RECONEXION_S,
                )
                time.sleep(RETARDO_RECONEXION_S)

    def _intentar_reabrir_serial(self) -> bool:
        try:
            self._puerto.abrir()
        except (OSError, ValueError) as error:
            REGISTRO.warning(
                "Reapertura de %s falló: %s; nuevo intento en %.0f s",
                self._configuracion.ruta_puerto_serie,
                error,
                RETARDO_RECONEXION_S,
            )
            time.sleep(RETARDO_RECONEXION_S)
            return False
        REGISTRO.info("Puerto serie reabierto; se pide estado al controlador")
        self._nucleo.volcar_estado_inicial()
        return True
