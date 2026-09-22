"""Simulador del controlador de la maqueta para probar el puente sin hardware (SPECS §4).

Emite latidos EST y una secuencia de eventos de ejemplo, responde CMD con RSP
tras una latencia configurable y atiende SYN reenviando su historial. Sirve
para la prueba temprana H2 del ROADMAP (apagar el servidor a mitad de un
trabajo y verificar modo degradado y reconciliación) y para depurar el
enlace serial con ``reproducir_captura.py``.

Ejemplos:
    python herramientas/simulador_controlador.py --puerto /dev/pts/3
    python herramientas/simulador_controlador.py --puerto /dev/ttyUSB0 --modo sin_latido
"""

import argparse
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from puente.enlace_serie import EnlaceSerie
from puente.protocolo import (
    TIPO_AUT,
    TIPO_CMD,
    TIPO_JOB,
    TIPO_PING,
    TIPO_RSP,
    TIPO_SYN,
    AnalizadorTramas,
    Trama,
)

REGISTRO = logging.getLogger("simulador")

PERIODO_LATIDO_S = 5.0
LATENCIA_RESPUESTA_S = 0.3
PERIODOS_SIN_SERVIDOR = 3

SECUENCIA_EVENTOS: list[tuple[str, dict[str, str]]] = [
    ("GAR", {"veh": "V01", "res": "ESPERA_AUT"}),
    ("PES", {"veh": "V01", "g": "38500", "n": "12", "meseta": "1"}),
    ("AGU", {"estado": "RECTA"}),
    ("TRF", {"evento": "ALINEADO", "veh": "V01"}),
    ("GRU", {"paso": "IZANDO", "pos": "P3", "nivel": "1", "cont": "C01"}),
    ("PAT", {"pos": "P3", "nivel": "1", "cont": "C01", "estado": "OCUPADA"}),
    ("SAL", {"veh": "V01", "res": "COINCIDE"}),
]

COMANDOS_RECHAZADOS: dict[str, str] = {
    "AbrirTalanquera": "VEH_BAJO_TALANQUERA",
    "AgujaLiberar": "PARQUEO_VACIO",
    "GruaReanudar": "GRUA_EN_FALLA",
}


@dataclass
class EstadoSimulador:
    """Estado mutable del simulador protegido por candado."""

    seq: int = 1000
    modo: str = "NORMAL"
    ultimo_mensaje_servidor_ms: float = field(default_factory=lambda: time.monotonic() * 1000)
    historial: list[Trama] = field(default_factory=list)
    respuestas: dict[int, tuple[str, str | None]] = field(default_factory=dict)
    candado: threading.Lock = field(default_factory=threading.Lock)


class SimuladorControlador:
    """Compañero de pruebas del lado del controlador sobre pySerial."""

    def __init__(
        self,
        ruta_puerto: str,
        baudios: int = 115200,
        intervalo_latido_s: float = PERIODO_LATIDO_S,
        latencia_respuesta_s: float = LATENCIA_RESPUESTA_S,
        modo: str = "normal",
    ) -> None:
        self._enlace = EnlaceSerie(ruta_puerto, baudios)
        self._intervalo_latido_s = intervalo_latido_s
        self._latencia_respuesta_s = latencia_respuesta_s
        self._modo_inicial = modo
        self._estado = EstadoSimulador()
        self._analizador = AnalizadorTramas()
        self._activo = threading.Event()
        self._hilos: list[threading.Thread] = []
        self._programadas: list[tuple[float, Trama]] = []
        self._candado_programadas = threading.Lock()

    def iniciar(self) -> None:
        self._activo.set()
        self._enlace.abrir()
        if self._modo_inicial == "sin_latido":
            self._estado.modo = "DEGRADADO"
        for objetivo in (self._ciclo_lector, self._ciclo_latido):
            hilo = threading.Thread(target=objeto_con_manejo, args=(objetivo,), daemon=True)
            hilo.start()
            self._hilos.append(hilo)
        REGISTRO.info("Simulador del controlador en operación")

    def detener(self) -> None:
        self._activo.clear()
        self._enlace.cerrar()

    @property
    def esta_activo(self) -> bool:
        """Indica si el simulador sigue en ejecución.

        Antes ``main()`` leía directamente el atributo privado
        ``simulador._activo`` desde fuera de la clase; esta propiedad es la
        forma pública de consultar lo mismo sin romper el encapsulamiento.
        """
        return self._activo.is_set()

    # ------------------------------------------------------------------ hilos

    def _ciclo_lector(self) -> None:
        while self._activo.is_set():
            datos = self._enlace.leer_disponible()
            if not datos:
                self._atender_programadas()
                time.sleep(0.01)
                continue
            with self._estado.candado:
                self._estado.ultimo_mensaje_servidor_ms = time.monotonic() * 1000
            for resultado in self._analizador.alimentar(datos):
                match resultado:
                    case Trama():
                        self._atender_trama_servidor(resultado)
                    case _:
                        REGISTRO.warning("Trama inválida descartada por el simulador")
            self._atender_programadas()

    def _ciclo_latido(self) -> None:
        siguiente_latido = time.monotonic() + self._intervalo_latido_s
        eventos_pendientes = list(SECUENCIA_EVENTOS)
        while self._activo.is_set():
            ahora = time.monotonic()
            if ahora >= siguiente_latido:
                self._detectar_modo_degradado()
                self._enviar_evento("EST", self._campos_latido())
                siguiente_latido = ahora + self._intervalo_latido_s
            if eventos_pendientes and self._estado.modo == "NORMAL":
                tipo, campos = eventos_pendientes.pop(0)
                self._enviar_evento(tipo, campos)
            time.sleep(0.05)

    def _detectar_modo_degradado(self) -> None:
        umbral_ms = self._intervalo_latido_s * PERIODOS_SIN_SERVIDOR * 1000
        ahora_ms = time.monotonic() * 1000
        with self._estado.candado:
            silencio_ms = ahora_ms - self._estado.ultimo_mensaje_servidor_ms
            modo_previo = self._estado.modo
            self._estado.modo = "DEGRADADO" if silencio_ms >= umbral_ms else "NORMAL"
        if modo_previo != "DEGRADADO" and self._estado.modo == "DEGRADADO":
            REGISTRO.warning("Sin mensajes del servidor: modo degradado (§3.3)")

    def _campos_latido(self) -> dict[str, str]:
        with self._estado.candado:
            return {
                "modo": self._estado.modo,
                "grua": "REPOSO",
                "aguja": "RECTA",
                "cola": "0",
                "espera": "0",
                "err": "0",
                "dif": "0",
                "link": "1",
            }

    # ------------------------------------------------------- tramas servidor

    def _atender_trama_servidor(self, trama: Trama) -> None:
        if trama.tipo == TIPO_PING:
            REGISTRO.debug("PING recibido (seq=%d)", trama.seq)
            return
        if trama.tipo in (TIPO_AUT, TIPO_JOB):
            REGISTRO.info("Mensaje de servicio %s recibido (seq=%d)", trama.tipo, trama.seq)
            return
        if trama.tipo == TIPO_CMD:
            self._programar_respuesta(trama)
            return
        if trama.tipo == TIPO_SYN:
            self._atender_syn(trama)

    def _programar_respuesta(self, trama: Trama) -> None:
        with self._estado.candado:
            respuesta_previa = self._estado.respuestas.get(trama.seq)
        if respuesta_previa is not None:
            estado, causa = respuesta_previa
        else:
            causa = COMANDOS_RECHAZADOS.get(trama.campos.get("nombre", ""))
            estado = "NAK" if causa else "ACK"
            with self._estado.candado:
                self._estado.respuestas[trama.seq] = (estado, causa)
        campos = {"estado": estado}
        if causa:
            campos["causa"] = causa
        respuesta = Trama(seq=trama.seq, tipo=TIPO_RSP, campos=campos)
        with self._candado_programadas:
            self._programadas.append((time.monotonic() + self._latencia_respuesta_s, respuesta))
        REGISTRO.info(
            "CMD %s (seq=%d) → RSP %s %s en %.1f s",
            trama.campos.get("nombre", "?"),
            trama.seq,
            estado,
            causa or "",
            self._latencia_respuesta_s,
        )

    def _atender_programadas(self) -> None:
        ahora = time.monotonic()
        vencidas: list[Trama] = []
        with self._candado_programadas:
            restantes: list[tuple[float, Trama]] = []
            for instante, trama in self._programadas:
                if instante <= ahora:
                    vencidas.append(trama)
                else:
                    restantes.append((instante, trama))
            self._programadas = restantes
        for trama in vencidas:
            self._enviar_trama(trama)

    def _atender_syn(self, trama: Trama) -> None:
        desde = trama.campos.get("desde")
        REGISTRO.info("SYN recibido: desde=%s estado=%s", desde, trama.campos.get("estado"))
        if desde is not None:
            limite = int(desde)
            with self._estado.candado:
                reenvio = [t for t in self._estado.historial if t.seq >= limite]
            for trama_historica in reenvio:
                self._enviar_trama(trama_historica)
            REGISTRO.info("Reenviadas %d tramas del historial", len(reenvio))

    # ---------------------------------------------------------------- envío

    def _enviar_evento(self, tipo: str, campos: dict[str, str]) -> None:
        with self._estado.candado:
            self._estado.seq += 1
            trama = Trama(seq=self._estado.seq, tipo=tipo, campos=campos)
            self._estado.historial.append(trama)
            self._estado.historial = self._estado.historial[-512:]
        self._enviar_trama(trama)

    def _enviar_trama(self, trama: Trama) -> None:
        try:
            self._enlace.escribir(trama.armar_linea().encode("ascii"))
        except RuntimeError as error:
            REGISTRO.error("No se pudo enviar trama: %s", error)


def objeto_con_manejo(ciclo: Callable[[], None]) -> None:
    """Envoltorio de ciclo de hilo con registro de fallos (CODESTYLE D-6)."""
    try:
        ciclo()
    except Exception:
        REGISTRO.exception("Fallo fatal en el ciclo del simulador")


def _leer_argumentos() -> argparse.Namespace:
    analizador = argparse.ArgumentParser(description="Simulador del controlador PORTUS")
    analizador.add_argument("--puerto", required=True, help="ruta del puerto serie")
    analizador.add_argument("--baudios", type=int, default=115200)
    analizador.add_argument("--intervalo-latido-s", type=float, default=PERIODO_LATIDO_S)
    analizador.add_argument("--latencia-respuesta-s", type=float, default=LATENCIA_RESPUESTA_S)
    analizador.add_argument(
        "--modo",
        choices=["normal", "sin_latido"],
        default="normal",
        help="sin_latido emula un controlador que dejó de latir (prueba de AL01)",
    )
    return analizador.parse_args()


def main() -> int:
    import signal

    logging.basicConfig(
        format="%(asctime)s.%(msecs)03dZ · %(levelname)s · %(name)s · %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        level=logging.INFO,
    )
    logging.Formatter.converter = time.gmtime
    argumentos = _leer_argumentos()
    simulador = SimuladorControlador(
        ruta_puerto=argumentos.puerto,
        baudios=argumentos.baudios,
        intervalo_latido_s=argumentos.intervalo_latido_s,
        latencia_respuesta_s=argumentos.latencia_respuesta_s,
        modo=argumentos.modo,
    )
    for nombre_senal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(nombre_senal, lambda senal, marco: simulador.detener())
    try:
        simulador.iniciar()
        while simulador.esta_activo:
            time.sleep(0.5)
    finally:
        simulador.detener()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
