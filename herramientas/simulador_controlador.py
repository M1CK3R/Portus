"""Simulador del controlador de la maqueta para probar el puente sin hardware (SPECS §4).

Emite latidos EST y una secuencia de eventos de ejemplo, responde CMD con RSP
tras una latencia configurable y atiende SYN reenviando su historial. Sirve
para la prueba temprana H2 del ROADMAP (apagar el servidor a mitad de un
trabajo y verificar modo degradado y reconciliación) y para depurar el
enlace serial con ``reproducir_captura.py``.

Con ``--interactivo`` no dispara la secuencia fija: cada evento se teclea
(``gar V01``, ``pes V01 45000``, ``trf V01``, ``grua``, ``sal V01``…) para
recorrer retenciones, abortos y órdenes manuales a ritmo humano; ``ayuda``
lista las órdenes. ``grua`` ejecuta el último ``JOB`` recibido del servidor.

Ejemplos:
    python herramientas/simulador_controlador.py --puerto /dev/pts/3
    python herramientas/simulador_controlador.py --puerto /dev/pts/3 --interactivo
    python herramientas/simulador_controlador.py --puerto /dev/ttyUSB0 --modo sin_latido
"""

import argparse
import copy
import logging
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from herramientas.enclavamientos_simulados import (
    MODO_MANTENIMIENTO,
    MODO_NORMAL,
    EstadoFisico,
    aplicar_efecto,
    evaluar_comando,
    fijar_sensor,
    resumen,
)
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

ORIGEN_VEHICULO = "VEH"
"""Marcador del vehículo en JOB.origen/destino (docs/protocolo_serial.md §3.2)."""
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
    ("GRU", {"paso": "FIN", "pos": "P3", "nivel": "1", "cont": "C01", "res": "OK"}),
    ("PES", {"veh": "V01", "g": "950", "n": "10", "meseta": "1"}),
    ("SAL", {"veh": "V01", "res": "DETECTADO"}),
    ("SAL", {"veh": "V01", "res": "CONFIRMADO"}),
]
"""Valores SAL [DEC]: DETECTADO llega a la puerta; CONFIRMADO pasó la puerta
(docs/protocolo_serial.md §3.1). El PES de salida usa la tara de V01 (950 g)."""


@dataclass
class EstadoSimulador:
    """Estado mutable del simulador protegido por candado."""

    seq: int = 1000
    modo: str = "NORMAL"
    ultimo_mensaje_servidor_ms: float = field(default_factory=lambda: time.monotonic() * 1000)
    historial: list[Trama] = field(default_factory=list)
    respuestas: dict[int, tuple[str, str | None]] = field(default_factory=dict)
    pendientes: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    ultimo_job: dict[str, str] = field(default_factory=dict)
    fisico: EstadoFisico = field(default_factory=EstadoFisico)
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
        secuencia: list[tuple[str, dict[str, str]]] | None = None,
        fisico: EstadoFisico | None = None,
    ) -> None:
        self._enlace = EnlaceSerie(ruta_puerto, baudios)
        self._intervalo_latido_s = intervalo_latido_s
        self._latencia_respuesta_s = latencia_respuesta_s
        self._modo_inicial = modo
        self._estado = EstadoSimulador()
        self._estado.pendientes = list(SECUENCIA_EVENTOS if secuencia is None else secuencia)
        if fisico is not None:
            self._estado.fisico = fisico
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

    def encolar(self, eventos: list[tuple[str, dict[str, str]]]) -> None:
        """Agrega eventos a emitir en orden (modo interactivo)."""
        with self._estado.candado:
            self._estado.pendientes.extend(eventos)

    def fijar_sensor(self, nombre: str, valor: str) -> None:
        """Simula un sensor o una falla física (consola ``sensor``); ValueError si no existe."""
        with self._estado.candado:
            fijar_sensor(nombre, valor, self._estado.fisico)

    def resumen_fisico(self) -> str:
        with self._estado.candado:
            return resumen(self._estado.fisico)

    def ultimo_job(self) -> dict[str, str]:
        """Campos del último JOB recibido del servidor (vacío si no llegó ninguno)."""
        with self._estado.candado:
            return dict(self._estado.ultimo_job)

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
        while self._activo.is_set():
            ahora = time.monotonic()
            if ahora >= siguiente_latido:
                self._detectar_modo_degradado()
                self._enviar_evento("EST", self.campos_latido())
                siguiente_latido = ahora + self._intervalo_latido_s
            with self._estado.candado:
                siguiente = (
                    self._estado.pendientes.pop(0)
                    if self._estado.pendientes and self._estado.modo == "NORMAL"
                    else None
                )
            if siguiente is not None:
                self._enviar_evento(*siguiente)
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

    def estado_fisico(self) -> EstadoFisico:
        """Copia del estado físico simulado (para pruebas y la orden ``estado``)."""
        with self._estado.candado:
            return copy.deepcopy(self._estado.fisico)

    def campos_latido(self) -> dict[str, str]:
        """Campos del latido EST con el modo y la grúa reales del simulador (§5.4)."""
        with self._estado.candado:
            fisico = self._estado.fisico
            modo = self._estado.modo
            if modo == MODO_NORMAL and fisico.mantenimiento:
                modo = MODO_MANTENIMIENTO
            return {
                "modo": modo,
                "grua": fisico.estado_grua,
                "aguja": fisico.aguja,
                "cola": "0",
                "espera": str(fisico.vehiculos_en_espera),
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
            REGISTRO.info("%s recibido (seq=%d): %s", trama.tipo, trama.seq, trama.campos)
            if trama.tipo == TIPO_JOB:
                with self._estado.candado:
                    self._estado.ultimo_job = dict(trama.campos)
            return
        if trama.tipo == TIPO_CMD:
            self._programar_respuesta(trama)
            return
        if trama.tipo == TIPO_SYN:
            self._atender_syn(trama)

    def responder_comando(self, seq: int, campos: dict[str, str]) -> tuple[str, str | None]:
        """Evalúa el enclavamiento una sola vez por SEQ y devuelve (ACK|NAK, causa).

        Un reintento con la misma SEQ recibe la misma respuesta y no vuelve a
        actuar (§4.5); con la condición de rechazo presente no se toca nada (§6.2).
        """
        nombre = campos.get("nombre", "")
        parametros = {k: v for k, v in campos.items() if k != "nombre"}
        with self._estado.candado:
            respuesta_previa = self._estado.respuestas.get(seq)
            if respuesta_previa is not None:
                return respuesta_previa
            causa = evaluar_comando(nombre, parametros, self._estado.fisico)
            if causa is None:
                aplicar_efecto(nombre, parametros, self._estado.fisico)
            respuesta = ("NAK" if causa else "ACK", causa)
            self._estado.respuestas[seq] = respuesta
        return respuesta

    def _programar_respuesta(self, trama: Trama) -> None:
        estado, causa = self.responder_comando(trama.seq, trama.campos)
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
        "--interactivo",
        action="store_true",
        help="sin secuencia fija: los eventos se teclean por la entrada estándar",
    )
    analizador.add_argument(
        "--modo",
        choices=["normal", "sin_latido"],
        default="normal",
        help="sin_latido emula un controlador que dejó de latir (prueba de AL01)",
    )
    return analizador.parse_args()


AYUDA_CONSOLA = """Órdenes (una por línea):
  gar V01                 vehículo identificado en garita (GAR)
  pes V01 45000           pesaje con meseta, peso bruto en g (PES)
  trf V01 [ABORTO]        vehículo alineado en transferencia, o aborto (TRF)
  grua                    ejecuta el último JOB del servidor: GRU IZANDO, PAT, GRU FIN OK
  grua-aborto             aborta el último JOB (GRU ABORTO, sin PAT)
  sal V01 [CONFIRMADO]    vehículo en la puerta de salida (DETECTADO por omisión)
  alm AL02 CRITICA        alarma del controlador (ALM)
  evt TIPO k=v k=v        trama libre, p. ej. «evt AGU estado=PARQUEO»
  sensor NOMBRE VALOR     condición física para los enclavamientos de §6.1:
                          talanquera|puerta|aguja|transferencia|carga|falla 1/0,
                          parqueo N, espera N (fila del latido, métrica 6),
                          trabajo P3|0, inconsistencia P2|0
  estado                  muestra sensores, actuadores y modo del simulador
  ayuda · salir"""


def _consola(simulador: SimuladorControlador) -> None:
    """Lee órdenes de la entrada estándar y las convierte en eventos (modo interactivo)."""
    sys.stdout.write(AYUDA_CONSOLA + "\n")
    for linea in sys.stdin:
        partes = linea.split()
        if not partes:
            continue
        if partes[0] == "salir":
            simulador.detener()
            return
        try:
            if _atender_orden_fisica(partes, simulador):
                continue
            eventos = _eventos_de_orden(partes, simulador.ultimo_job())
        except (IndexError, KeyError, ValueError) as error:
            sys.stdout.write(f"orden inválida ({error}); escriba «ayuda»\n")
            continue
        if eventos is None:
            sys.stdout.write(AYUDA_CONSOLA + "\n")
            continue
        simulador.encolar(eventos)


def _atender_orden_fisica(partes: list[str], simulador: SimuladorControlador) -> bool:
    """Órdenes que cambian o muestran el estado físico; True si la orden era de este tipo.

    ``trf … ALINEADO`` deja un vehículo en transferencia (enclavamiento de
    ModoMantenimiento) y el siguiente ``pes`` lo saca; luego se emite el evento.
    """
    orden = partes[0]
    if orden == "sensor":
        simulador.fijar_sensor(partes[1], partes[2])
        sys.stdout.write(simulador.resumen_fisico() + "\n")
        return True
    if orden == "estado":
        sys.stdout.write(simulador.resumen_fisico() + "\n")
        return True
    if orden == "trf":
        alineado = len(partes) < 3 or partes[2] == "ALINEADO"
        simulador.fijar_sensor("transferencia", "1" if alineado else "0")
    if orden == "pes":
        simulador.fijar_sensor("transferencia", "0")
    return False


def _eventos_de_orden(
    partes: list[str], job: dict[str, str]
) -> list[tuple[str, dict[str, str]]] | None:
    """Traduce una orden de consola a tramas del controlador; None si es «ayuda»."""
    orden, argumentos = partes[0], partes[1:]
    match orden:
        case "gar":
            return [("GAR", {"veh": argumentos[0], "res": "ESPERA_AUT"})]
        case "pes":
            peso_g = str(int(argumentos[1]))
            return [("PES", {"veh": argumentos[0], "g": peso_g, "n": "12", "meseta": "1"})]
        case "trf":
            evento = argumentos[1] if len(argumentos) > 1 else "ALINEADO"
            return [("TRF", {"evento": evento, "veh": argumentos[0]})]
        case "sal":
            resultado = argumentos[1] if len(argumentos) > 1 else "DETECTADO"
            return [("SAL", {"veh": argumentos[0], "res": resultado})]
        case "alm":
            return [("ALM", {"cod": argumentos[0], "sev": argumentos[1]})]
        case "grua":
            return _eventos_de_job(job, abortar=False)
        case "grua-aborto":
            return _eventos_de_job(job, abortar=True)
        case "evt":
            campos = dict(par.split("=", 1) for par in argumentos[1:])
            return [(argumentos[0], campos)]
        case _:
            return None


def _eventos_de_job(job: dict[str, str], abortar: bool) -> list[tuple[str, dict[str, str]]]:
    """GRU/PAT que confirman físicamente el JOB (§12.3: el inventario cambia con PAT)."""
    if not job:
        raise ValueError("aún no llegó ningún JOB del servidor (¿faltó «trf»?)")
    contenedor = job["cont"]
    origen_pos, origen_nivel = _celda(job["origen"], job["nivel"])
    destino_pos, destino_nivel = _celda(job["destino"], job["nivel"])
    en_patio = destino_pos if destino_pos != ORIGEN_VEHICULO else origen_pos
    izando = {"paso": "IZANDO", "pos": en_patio, "nivel": job["nivel"], "cont": contenedor}
    if abortar:
        aborto = {"paso": "ABORTO", "pos": en_patio, "cont": contenedor, "res": "ABORTADO"}
        return [("GRU", izando), ("GRU", aborto)]
    if destino_pos == ORIGEN_VEHICULO:
        pat = {"pos": origen_pos, "nivel": origen_nivel, "cont": contenedor, "estado": "LIBRE"}
    else:
        pat = {"pos": destino_pos, "nivel": destino_nivel, "cont": contenedor, "estado": "OCUPADA"}
    fin = {"paso": "FIN", "pos": en_patio, "nivel": job["nivel"], "cont": contenedor, "res": "OK"}
    return [("GRU", izando), ("PAT", pat), ("GRU", fin)]


def _celda(texto: str, nivel_por_omision: str) -> tuple[str, str]:
    """«P3/N2» → (P3, 2); «P1» o «VEH» → (texto, nivel del JOB)."""
    posicion, _, nivel = texto.partition("/N")
    return posicion, nivel or nivel_por_omision


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
        secuencia=[] if argumentos.interactivo else None,
    )
    for nombre_senal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(nombre_senal, lambda senal, marco: simulador.detener())
    try:
        simulador.iniciar()
        if argumentos.interactivo:
            _consola(simulador)
        while simulador.esta_activo:
            time.sleep(0.5)
    finally:
        simulador.detener()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
