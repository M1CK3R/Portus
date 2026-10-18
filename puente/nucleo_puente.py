"""Núcleo del puente serial ↔ MQTT (SPECS §4, §5, §5.4, §6.4).

Lógica de procesamiento sin hilos propia (CODESTYLE T-3): el orquestador de
``puente.py`` la alimenta desde sus hilos. Aquí vive el flujo completo:

* Serial → MQTT: tramas validadas, rastreo de SEQ, SYN ante saltos, latido
  hacia el vigilante, publicación con el envoltorio único (§4.2, §4.3, §5).
* MQTT → Serial: ``portus/cmd/solicitud`` → trama CMD; RSP del controlador →
  ``portus/cmd/respuesta``; NAK sintético ``SIN_RESPUESTA`` a los 2 s (§6.4, §4.5).
* Vigilancia: tres periodos sin latido → AL01 y estado de enlace (§5.4);
  al recuperar el enlace se pide reconciliación con SYN (§3.3).
"""

import json
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from puente.enlace_serie import PuertoSerie
from puente.gestor_comandos import GestorComandos, SolicitudComando
from puente.mensajes_mqtt import (
    TIPO_EVENTO_COMANDO_SOLICITUD,
    TOPICO_CMD_SOLICITUD,
    TOPICO_SRV_TURNO,
    marca_tiempo_utc,
)
from puente.persistencia_sqlite import PersistenciaSqlite
from puente.protocolo import (
    ESTADO_ACK,
    ESTADO_NAK,
    TIPO_AUT,
    TIPO_EST,
    TIPO_JOB,
    TIPO_RSP,
    AnalizadorTramas,
    ResultadoAnalisis,
    Trama,
    TramaDescartada,
    armar_trama_servidor,
)
from puente.publicador_eventos import PublicadorEventos
from puente.secuencia import ClaseSecuencia, EmisorTramasServidor, RastreadorSecuencia
from puente.vigilante_latido import (
    EstadoEnlace,
    VigilanteLatido,
    datos_al01,
    evaluar_al01_retroactiva,
)

REGISTRO = logging.getLogger(__name__)


@dataclass
class ContadoresPuente:
    """Contadores de operación expuestos en el estado del enlace (§4.2, §5.4)."""

    tramas_validas: int = 0
    tramas_invalidas: int = 0
    bytes_descartados: int = 0
    saltos_secuencia: int = 0
    latidos_recibidos: int = 0
    comandos_sin_respuesta: int = 0

    def como_diccionario(self) -> dict[str, int]:
        return {
            "tramas_validas": self.tramas_validas,
            "tramas_invalidas": self.tramas_invalidas,
            "bytes_descartados": self.bytes_descartados,
            "saltos_secuencia": self.saltos_secuencia,
            "latidos_recibidos": self.latidos_recibidos,
            "comandos_sin_respuesta": self.comandos_sin_respuesta,
        }


@dataclass
class EstadoCompartido:
    """Estado mutable compartido entre hilos, protegido por un candado."""

    contadores: ContadoresPuente = field(default_factory=ContadoresPuente)
    ultimo_latido_ts: str | None = None
    candado: threading.Lock = field(default_factory=threading.Lock)


TIPO_MQTT_TURNO_AUTORIZACION = "turno.autorizacion"
TIPO_MQTT_TURNO_TRABAJO = "turno.trabajo"

MAX_IDS_SRV_VISTOS = 1024
"""Ventana de deduplicación de mensajes srv/ (QoS 1 puede reentregar, §5.5)."""


class NucleoPuente:
    """Ensambla protocolo, secuencia, comandos y vigilancia; sin hilos ni I/O de red."""

    def __init__(
        self,
        puerto: PuertoSerie,
        publicador: PublicadorEventos,
        gestor: GestorComandos,
        emisor: EmisorTramasServidor,
        vigilante: VigilanteLatido,
        persistencia: PersistenciaSqlite,
        reloj_ms: Callable[[], int],
        reloj_utc: Callable[[], datetime] | None = None,
    ) -> None:
        self._puerto = puerto
        self._publicador = publicador
        self._gestor = gestor
        self._emisor = emisor
        self._vigilante = vigilante
        self._persistencia = persistencia
        self._reloj_ms = reloj_ms
        self._reloj_utc = reloj_utc if reloj_utc is not None else _ahora_utc
        self._analizador = AnalizadorTramas()
        self._rastreador = RastreadorSecuencia()
        self._estado = EstadoCompartido()
        self._candado_escritura = threading.Lock()
        self._ids_srv_vistos: OrderedDict[str, None] = OrderedDict()

    @property
    def estado(self) -> EstadoCompartido:
        return self._estado

    @property
    def vigilante(self) -> VigilanteLatido:
        return self._vigilante

    @property
    def persistencia(self) -> PersistenciaSqlite:
        return self._persistencia

    # ------------------------------------------------------------------ serial

    def procesar_bytes(self, datos: bytes) -> list[ResultadoAnalisis]:
        """Alimenta el analizador y procesa cada trama completa (no bloqueante)."""
        resultados = self._analizador.alimentar(datos)
        for resultado in resultados:
            match resultado:
                case Trama():
                    self._procesar_trama(resultado)
                case TramaDescartada():
                    self._registrar_descarte(resultado)
        return resultados

    def _registrar_descarte(self, descartada: TramaDescartada) -> None:
        with self._estado.candado:
            self._estado.contadores.tramas_invalidas += 1
            if descartada.motivo == "bytes_sin_inicio":
                self._estado.contadores.bytes_descartados += 1
        REGISTRO.warning("Trama descartada (%s): %s", descartada.motivo, descartada.detalle)

    def _procesar_trama(self, trama: Trama) -> None:
        with self._estado.candado:
            self._estado.contadores.tramas_validas += 1
        if trama.tipo == TIPO_RSP:
            self._procesar_respuesta(trama)
            return
        if trama.tipo == TIPO_EST:
            self._registrar_latido()
        self._verificar_secuencia(trama)
        self._publicador.publicar_evento_controlador(trama)
        REGISTRO.info("Evento del controlador publicado: tipo=%s seq=%d", trama.tipo, trama.seq)

    def _procesar_respuesta(self, trama: Trama) -> None:
        estado = trama.campos.get("estado", "")
        causa = trama.campos.get("causa")
        if estado not in (ESTADO_ACK, ESTADO_NAK):
            REGISTRO.warning(
                "RSP con estado desconocido '%s' (seq=%d); se descarta", estado, trama.seq
            )
            return
        respuesta = self._gestor.resolver_respuesta(trama.seq, estado, causa)
        if respuesta is not None:
            self._publicador.publicar_respuesta_comando(respuesta)
            if respuesta.cmd_id is not None:
                self._persistencia.registrar_comando_resuelto(
                    respuesta.cmd_id, estado, causa, respuesta.tardia
                )
            REGISTRO.info(
                "Respuesta del controlador: cmd_id=%s estado=%s causa=%s",
                respuesta.cmd_id,
                estado,
                causa,
            )

    def _verificar_secuencia(self, trama: Trama) -> None:
        evento = self._rastreador.registrar(trama.seq)
        if evento.clase is not ClaseSecuencia.SALTO:
            return
        with self._estado.candado:
            self._estado.contadores.saltos_secuencia += 1
        self._publicador.publicar_salto_secuencia(evento)
        seq_previa = evento.seq_previa if evento.seq_previa is not None else 0
        trama_syn = self._emisor.armar_syn(desde=seq_previa + 1)
        self.enviar_trama(trama_syn)
        REGISTRO.warning(
            "Salto de SEQ: esperada %d, recibida %d; SYN desde=%d enviado",
            seq_previa + 1,
            evento.seq,
            seq_previa + 1,
        )

    def _registrar_latido(self) -> None:
        ahora_ms = self._reloj_ms()
        estado_previo = self._vigilante.estado
        self._vigilante.registrar_latido(ahora_ms)
        ts = marca_tiempo_utc(self._reloj_utc())
        with self._estado.candado:
            self._estado.contadores.latidos_recibidos += 1
            self._estado.ultimo_latido_ts = ts
        self._persistencia.registrar_latido(ts)
        if estado_previo is EstadoEnlace.PERDIDO:
            self._publicador.publicar_estado_enlace(
                EstadoEnlace.ACTIVO, ts, self._contadores_snapshot()
            )
            self._enviar_syn_reconciliacion()
            REGISTRO.info("Enlace con el controlador restablecido; SYN de reconciliación")

    def _enviar_syn_reconciliacion(self) -> None:
        seq_previa = self._rastreador.seq_previa
        desde = seq_previa + 1 if seq_previa is not None else None
        trama_syn = self._emisor.armar_syn(desde=desde, volcar_estado=True)
        self.enviar_trama(trama_syn)

    def enviar_trama(self, trama: Trama) -> None:
        """Envía una trama S→C por el puerto; escritura protegida por candado."""
        with self._candado_escritura:
            self._puerto.escribir(trama.armar_linea().encode("ascii"))

    def emitir_ping(self) -> None:
        """Emite el PING de vigilancia hacia el controlador (SPECS §3.4, A13)."""
        trama_ping = armar_trama_servidor(self._emisor.contador, "PING", {})
        self.enviar_trama(trama_ping)
        REGISTRO.debug("PING enviado (seq=%d)", trama_ping.seq)

    def volcar_estado_inicial(self) -> None:
        """Pide al controlador estado y eventos acumulados al abrir el enlace (§3.3)."""
        self._enviar_syn_reconciliacion()
        REGISTRO.info("SYN inicial enviado para volcar estado y eventos acumulados")

    # -------------------------------------------------------------- vigilancia

    def comprobar_vigilante(self) -> bool:
        """Evalúa el umbral del latido; publica AL01 y estado al perder el enlace."""
        transicion = self._vigilante.comprobar(self._reloj_ms())
        if transicion is None:
            return False
        self._publicador.publicar_alarma_enlace(datos_al01(transicion.ms_sin_latido))
        self._publicador.publicar_estado_enlace(
            EstadoEnlace.PERDIDO,
            self._estado.ultimo_latido_ts,
            self._contadores_snapshot(),
        )
        self._persistencia.actualizar_estado_enlace(
            "perdido", self._estado.ultimo_latido_ts, marca_tiempo_utc(self._reloj_utc())
        )
        REGISTRO.error(
            "AL01: enlace perdido tras %d ms sin latido (umbral de tres periodos)",
            transicion.ms_sin_latido,
        )
        return True

    def alarma_retroactiva_si_aplica(self) -> bool:
        """A14: al arrancar, registra AL01 retroactiva si hubo caída previa del enlace."""
        ultimo_ts = self._persistencia.ultimo_latido_ts()
        datos = evaluar_al01_retroactiva(ultimo_ts, self._reloj_utc(), self._umbral_ms())
        if datos is None:
            return False
        self._publicador.publicar_alarma_enlace(datos)
        REGISTRO.error("AL01 retroactiva registrada: pérdida previa de enlace desde %s", ultimo_ts)
        return True

    def _umbral_ms(self) -> int:
        return self._vigilante.umbral_ms

    # ------------------------------------------------------------------- MQTT

    def atender_mensaje_mqtt(self, topico: str, datos: bytes) -> None:
        """Enruta los mensajes del broker: persistencia para todos, comandos al gestor."""
        try:
            contenido = json.loads(datos.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            REGISTRO.warning("Mensaje MQTT mal formado en %s: %s", topico, error)
            return
        if not isinstance(contenido, dict):
            REGISTRO.warning("Mensaje MQTT sin objeto JSON en %s", topico)
            return
        id_mensaje = contenido.get("id")
        ts_mensaje = contenido.get("ts")
        tipo = contenido.get("tipo")
        if (
            not isinstance(id_mensaje, str)
            or not isinstance(ts_mensaje, str)
            or not isinstance(tipo, str)
        ):
            REGISTRO.warning("Mensaje MQTT sin id/ts/tipo válidos en %s", topico)
            return
        origen = contenido.get("origen", "")
        seq = contenido.get("seq")
        seq_valor = seq if isinstance(seq, int) else None
        datos_evento = contenido.get("datos", {})
        if not isinstance(datos_evento, dict):
            datos_evento = {}
        self._persistencia.guardar_evento(
            id_mensaje,
            ts_mensaje,
            str(origen),
            tipo,
            seq_valor,
            cast(dict[str, object], datos_evento),
            topico,
        )
        if topico == TOPICO_CMD_SOLICITUD and tipo == TIPO_EVENTO_COMANDO_SOLICITUD:
            self._atender_solicitud_comando(cast(dict[str, object], datos_evento), ts_mensaje)
            return
        if topico == TOPICO_SRV_TURNO and tipo == TIPO_MQTT_TURNO_AUTORIZACION:
            self._reenviar_aut(cast(dict[str, object], datos_evento), id_mensaje)
            return
        if topico == TOPICO_SRV_TURNO and tipo == TIPO_MQTT_TURNO_TRABAJO:
            self._reenviar_job(cast(dict[str, object], datos_evento), id_mensaje)

    def _primera_vez_srv(self, id_mensaje: str) -> bool:
        """Dedup por id de los mensajes srv/ que se convierten en serial (§5.5)."""
        if id_mensaje in self._ids_srv_vistos:
            return False
        self._ids_srv_vistos[id_mensaje] = None
        if len(self._ids_srv_vistos) > MAX_IDS_SRV_VISTOS:
            self._ids_srv_vistos.popitem(last=False)
        return True

    def _reenviar_aut(self, datos: dict[str, object], id_mensaje: str) -> None:
        """Convierte la decisión de garita en una trama AUT hacia el controlador (§4.4)."""
        if not self._primera_vez_srv(id_mensaje):
            REGISTRO.info("AUT duplicada (%s): no se reenvía al serial", id_mensaje)
            return
        campos: dict[str, str] = {"res": str(datos.get("resultado", "RECHAZADO"))}
        if datos.get("causa") is not None:
            campos["causa"] = str(datos["causa"])
        else:
            for clave_json, clave_serial in (
                ("turno", "turno"),
                ("veh", "veh"),
                ("tipo_op", "tipo"),
                ("peso_decl_g", "decl"),
                ("tol_pct", "tol"),
                ("canal", "canal"),
                ("pos_asignada", "pos"),
                ("nivel", "nivel"),
            ):
                valor = datos.get(clave_json)
                if valor is not None:
                    campos[clave_serial] = str(valor)
        trama = self._emisor.armar_mensaje(TIPO_AUT, campos)
        self.enviar_trama(trama)
        REGISTRO.info("AUT enviada al controlador: res=%s seq=%d", campos["res"], trama.seq)

    def _reenviar_job(self, datos: dict[str, object], id_mensaje: str) -> None:
        """Convierte un trabajo de grúa del servidor en una trama JOB (§4.4)."""
        if not self._primera_vez_srv(id_mensaje):
            REGISTRO.info("JOB duplicado (%s): no se reenvía al serial", id_mensaje)
            return
        campos: dict[str, str] = {
            "id": str(datos.get("trabajo", "")),
            "tipo": str(datos.get("tipo", "")),
            "origen": str(datos.get("origen", "")),
            "destino": str(datos.get("destino", "")),
            "nivel": str(datos.get("nivel", "")),
            "cont": str(datos.get("contenedor", "")),
            "turno": str(datos.get("turno", "")),
        }
        trama = self._emisor.armar_mensaje(TIPO_JOB, campos)
        self.enviar_trama(trama)
        REGISTRO.info(
            "JOB enviado al controlador: id=%s tipo=%s seq=%d",
            campos["id"],
            campos["tipo"],
            trama.seq,
        )

    def _atender_solicitud_comando(self, datos: dict[str, object], ts: str) -> None:
        cmd_id = datos.get("cmd_id")
        nombre = datos.get("nombre")
        if not isinstance(cmd_id, str) or not isinstance(nombre, str):
            REGISTRO.warning("cmd/solicitud sin cmd_id o nombre válidos; descartada")
            return
        usuario = datos.get("usuario", "")
        parametros = _parametros_texto(datos.get("parametros", {}))
        solicitud = SolicitudComando(
            cmd_id=cmd_id, nombre=nombre, parametros=parametros, usuario=str(usuario)
        )
        despacho = self._gestor.enviar_solicitud(solicitud)
        if despacho.respuesta_inmediata is not None:
            self._publicador.publicar_respuesta_comando(despacho.respuesta_inmediata)
            return
        if despacho.trama_enviada is None:
            return
        self._persistencia.registrar_comando_solicitado(
            cmd_id, ts, str(usuario), nombre, parametros, despacho.trama_enviada.seq
        )
        self.enviar_trama(despacho.trama_enviada)
        REGISTRO.info(
            "CMD enviado: cmd_id=%s nombre=%s seq=%d usuario=%s",
            cmd_id,
            nombre,
            despacho.trama_enviada.seq,
            usuario,
        )

    def expirar_comandos(self) -> int:
        """Publica NAK sintéticos SIN_RESPUESTA de las esperas vencidas (§4.5)."""
        sinteticas = self._gestor.expirar_esperas()
        if not sinteticas:
            return 0
        with self._estado.candado:
            self._estado.contadores.comandos_sin_respuesta += len(sinteticas)
        for respuesta in sinteticas:
            self._publicador.publicar_respuesta_comando(respuesta)
            if respuesta.cmd_id is not None:
                self._persistencia.registrar_comando_resuelto(
                    respuesta.cmd_id, respuesta.estado, respuesta.causa, respuesta.tardia
                )
        return len(sinteticas)

    def publicar_estado_enlace(self) -> None:
        self._publicador.publicar_estado_enlace(
            self._vigilante.estado,
            self._estado.ultimo_latido_ts,
            self._contadores_snapshot(),
        )

    # ------------------------------------------------------------------ utils

    def _contadores_snapshot(self) -> dict[str, int]:
        with self._estado.candado:
            return self._estado.contadores.como_diccionario()


def _ahora_utc() -> datetime:
    return datetime.now(UTC)


def _parametros_texto(valor: object) -> dict[str, str]:
    if not isinstance(valor, dict):
        return {}
    return {str(clave): str(dato) for clave, dato in valor.items()}
