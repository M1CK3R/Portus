"""Flujo de un comando remoto del servidor hacia el controlador (SPECS §6.4, §4.5).

Ciclo completo (§6.4): ``portus/cmd/solicitud`` → trama CMD con SEQ y CRC →
el controlador responde ``RSP`` con el mismo SEQ → ``portus/cmd/respuesta``.
Sin respuesta en 2 s el puente publica un NAK sintético con causa
``SIN_RESPUESTA`` (§4.5). Un cmd_id reenviado reutiliza la misma SEQ para que
el controlador responda de forma idempotente sin repetir la acción física.

La lógica es reloj-inyectable y libre de hilos (CODESTYLE T-3): el orquestador
llama a ``expirar_esperas`` y ``resolver_respuesta`` desde sus hilos.
"""

import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from puente.protocolo import (
    CAUSA_COMANDO_DESCONOCIDO,
    CAUSA_SIN_RESPUESTA,
    ESTADO_NAK,
    NOMBRES_COMANDOS,
    TIPO_CMD,
    Trama,
)
from puente.secuencia import EmisorTramasServidor
from puente.tiempo import MS_POR_SEGUNDO, reloj_monotonico_ms

REGISTRO = logging.getLogger(__name__)

TIEMPO_LIMITE_COMANDO_S = 2.0
CAPACIDAD_MAPA_CMD_SEQ = 256


@dataclass(frozen=True)
class SolicitudComando:
    """Comando recibido en portus/cmd/solicitud, ya validado en la frontera."""

    cmd_id: str
    nombre: str
    parametros: dict[str, str]
    usuario: str


@dataclass(frozen=True)
class RespuestaComando:
    """Respuesta para portus/cmd/respuesta, real o sintética."""

    cmd_id: str | None
    nombre: str
    seq: int
    estado: str
    causa: str | None
    sintetica: bool
    tardia: bool


@dataclass(frozen=True)
class DespachoComando:
    """Resultado de atender una solicitud: trama a enviar y/o respuesta inmediata.

    ``trama_enviada`` es None cuando no hay nada que mandar por serial;
    ``respuesta_inmediata`` es un NAK cuando la solicitud se rechaza en la
    frontera (comando desconocido). Ambos None: duplicado en vuelo.
    """

    trama_enviada: Trama | None
    respuesta_inmediata: RespuestaComando | None


@dataclass
class _EsperaRespuesta:
    cmd_id: str
    nombre: str
    enviada_ms: int
    resuelta: bool


class GestorComandos:
    """Administra la correlación cmd_id ↔ SEQ y el tiempo límite de 2 s (§4.5)."""

    def __init__(
        self,
        emisor: EmisorTramasServidor,
        tiempo_limite_s: float = TIEMPO_LIMITE_COMANDO_S,
        reloj_ms: Callable[[], int] = reloj_monotonico_ms,
    ) -> None:
        self._emisor = emisor
        self._tiempo_limite_ms = int(tiempo_limite_s * MS_POR_SEGUNDO)
        self._reloj_ms = reloj_ms
        self._esperas: dict[int, _EsperaRespuesta] = {}
        self._esperas_resueltas: dict[int, _EsperaRespuesta] = {}
        self._seq_por_cmd: dict[str, int] = {}
        self._orden_cmd: deque[str] = deque()
        self._orden_resueltas: deque[int] = deque()
        self._candado = threading.Lock()

    def enviar_solicitud(self, solicitud: SolicitudComando) -> DespachoComando:
        """Valida el comando, asigna SEQ y registra la espera de la RSP.

        Devuelve la trama CMD a enviar por serial. Si el nombre no pertenece al
        catálogo devuelve el NAK inmediato ``COMANDO_DESCONOCIDO`` sin enviar
        trama. Si el cmd_id ya está en vuelo (QoS 1 puede duplicar) devuelve un
        despacho vacío para no reenviar ni duplicar la espera.
        """
        with self._candado:
            if solicitud.nombre not in NOMBRES_COMANDOS:
                REGISTRO.error(
                    "cmd_id=%s: nombre de comando desconocido '%s'; NAK sin enviar trama",
                    solicitud.cmd_id,
                    solicitud.nombre,
                )
                respuesta = RespuestaComando(
                    cmd_id=solicitud.cmd_id,
                    nombre=solicitud.nombre,
                    seq=0,
                    estado=ESTADO_NAK,
                    causa=CAUSA_COMANDO_DESCONOCIDO,
                    sintetica=True,
                    tardia=False,
                )
                return DespachoComando(trama_enviada=None, respuesta_inmediata=respuesta)
            seq_asignada = self._seq_por_cmd.get(solicitud.cmd_id)
            es_reintento = seq_asignada is not None
            if seq_asignada is None:
                seq_asignada = self._emisor.contador.siguiente()
                self._seq_por_cmd[solicitud.cmd_id] = seq_asignada
                self._orden_cmd.append(solicitud.cmd_id)
                while len(self._orden_cmd) > CAPACIDAD_MAPA_CMD_SEQ:
                    cmd_antiguo = self._orden_cmd.popleft()
                    self._seq_por_cmd.pop(cmd_antiguo, None)
            espera = self._esperas.get(seq_asignada)
            if espera is not None and not espera.resuelta:
                REGISTRO.warning(
                    "cmd_id=%s duplicado en vuelo (seq=%d); se ignora la copia",
                    solicitud.cmd_id,
                    seq_asignada,
                )
                return DespachoComando(trama_enviada=None, respuesta_inmediata=None)
            self._esperas[seq_asignada] = _EsperaRespuesta(
                cmd_id=solicitud.cmd_id,
                nombre=solicitud.nombre,
                enviada_ms=self._reloj_ms(),
                resuelta=False,
            )
            if es_reintento:
                REGISTRO.info(
                    "cmd_id=%s reenviado con seq=%d para idempotencia (§4.5)",
                    solicitud.cmd_id,
                    seq_asignada,
                )
            trama = Trama(
                seq=seq_asignada,
                tipo=TIPO_CMD,
                campos={"nombre": solicitud.nombre, **solicitud.parametros},
            )
            return DespachoComando(trama_enviada=trama, respuesta_inmediata=None)

    def resolver_respuesta(
        self, seq: int, estado: str, causa: str | None
    ) -> RespuestaComando | None:
        """Correlaciona una trama RSP del controlador con la espera del comando."""
        with self._candado:
            espera = self._esperas.get(seq)
            if espera is None:
                espera_resuelta = self._esperas_resueltas.get(seq)
                if espera_resuelta is None:
                    REGISTRO.warning(
                        "RSP sin comando pendiente (seq=%d, estado=%s, causa=%s)",
                        seq,
                        estado,
                        causa,
                    )
                    return None
                REGISTRO.warning(
                    "cmd_id=%s: RSP tardía tras NAK sintético (seq=%d, estado=%s)",
                    espera_resuelta.cmd_id,
                    seq,
                    estado,
                )
                return RespuestaComando(
                    cmd_id=espera_resuelta.cmd_id,
                    nombre=espera_resuelta.nombre,
                    seq=seq,
                    estado=estado,
                    causa=causa,
                    sintetica=False,
                    tardia=True,
                )
            espera.resuelta = True
            self._archivar_resuelta(seq, espera)
            return RespuestaComando(
                cmd_id=espera.cmd_id,
                nombre=espera.nombre,
                seq=seq,
                estado=estado,
                causa=causa,
                sintetica=False,
                tardia=False,
            )

    def expirar_esperas(self) -> list[RespuestaComando]:
        """Genera NAK sintéticos SIN_RESPUESTA para las esperas vencidas (§4.5)."""
        ahora_ms = self._reloj_ms()
        sinteticas: list[RespuestaComando] = []
        with self._candado:
            for seq, espera in self._esperas.items():
                if espera.resuelta:
                    continue
                if ahora_ms - espera.enviada_ms < self._tiempo_limite_ms:
                    continue
                espera.resuelta = True
                self._archivar_resuelta(seq, espera)
                REGISTRO.error(
                    "cmd_id=%s: sin respuesta del controlador en %d ms (seq=%d); NAK sintético %s",
                    espera.cmd_id,
                    ahora_ms - espera.enviada_ms,
                    seq,
                    CAUSA_SIN_RESPUESTA,
                )
                sinteticas.append(
                    RespuestaComando(
                        cmd_id=espera.cmd_id,
                        nombre=espera.nombre,
                        seq=seq,
                        estado=ESTADO_NAK,
                        causa=CAUSA_SIN_RESPUESTA,
                        sintetica=True,
                        tardia=False,
                    )
                )
            pendientes = [seq for seq, espera in self._esperas.items() if espera.resuelta]
            for seq in pendientes:
                del self._esperas[seq]
        return sinteticas

    def _archivar_resuelta(self, seq: int, espera: _EsperaRespuesta) -> None:
        """Mueve la espera resuelta al registro de recientes para detectar RSP tardías."""
        self._esperas_resueltas[seq] = espera
        self._orden_resueltas.append(seq)
        while len(self._orden_resueltas) > CAPACIDAD_MAPA_CMD_SEQ:
            seq_antigua = self._orden_resueltas.popleft()
            self._esperas_resueltas.pop(seq_antigua, None)

    @property
    def tiempo_limite_ms(self) -> int:
        return self._tiempo_limite_ms
