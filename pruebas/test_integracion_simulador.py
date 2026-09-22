"""Prueba de integración extremo a extremo: simulador ↔ EnlaceSerie ↔ núcleo.

Crea un par de PTY del kernel: el simulador del controlador (pySerial) abre el
extremo esclavo y el núcleo del puente lee del maestro mediante un adaptador
PuertoSerie. Verifica el ciclo completo de la Etapa 3 sin maqueta ni broker:
latidos publicados (§5.4), comando → trama CMD → RSP → respuesta publicada
(§6.4) y envío de PING/SYN (§3.4, §4.2).
"""

import json
import os
import select
import time
import tty

import pytest

from herramientas.simulador_controlador import SimuladorControlador
from pruebas.utilidades_pruebas import SalidaFalsa
from puente.gestor_comandos import GestorComandos
from puente.nucleo_puente import NucleoPuente
from puente.persistencia_sqlite import PersistenciaSqlite
from puente.publicador_eventos import PublicadorEventos
from puente.secuencia import ContadorSecuenciaServidor, EmisorTramasServidor
from puente.vigilante_latido import VigilanteLatido

PLAZO_ESPERA_S = 3.0
MS_POR_SEGUNDO = 1000


class PuertoSerieMaestro:
    """Adaptador PuertoSerie sobre el extremo maestro de un par de PTY."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor

    def abrir(self) -> None:
        pass

    def cerrar(self) -> None:
        pass

    @property
    def esta_abierto(self) -> bool:
        return True

    def leer_disponible(self) -> bytes:
        listo, _, _ = select.select([self._descriptor], [], [], 0)
        if not listo:
            return b""
        return os.read(self._descriptor, 4096)

    def escribir(self, datos: bytes) -> None:
        os.write(self._descriptor, datos)


def _esperar_publicacion(
    nucleo: NucleoPuente,
    maestro: PuertoSerieMaestro,
    salida: SalidaFalsa,
    condicion,
    plazo_s: float,
) -> bool:
    limite = time.monotonic() + plazo_s
    while time.monotonic() < limite:
        datos = maestro.leer_disponible()
        if datos:
            nucleo.procesar_bytes(datos)
        if any(condicion(p) for p in salida.publicaciones):
            return True
        time.sleep(0.02)
    return False


def _bombeo(nucleo: NucleoPuente, maestro: PuertoSerieMaestro, duracion_s: float) -> None:
    """Lee del puerto y alimenta el núcleo durante un plazo, como el hilo lector."""
    limite = time.monotonic() + duracion_s
    while time.monotonic() < limite:
        datos = maestro.leer_disponible()
        if datos:
            nucleo.procesar_bytes(datos)
        else:
            time.sleep(0.01)


@pytest.fixture()
def canal_pty():
    maestro_fd, esclavo_fd = os.openpty()
    tty.setraw(esclavo_fd)
    ruta_esclavo = os.ttyname(esclavo_fd)
    yield ruta_esclavo, PuertoSerieMaestro(maestro_fd)
    os.close(esclavo_fd)
    os.close(maestro_fd)


def test_ciclo_completo_con_simulador_sobre_pty(tmp_path, canal_pty):
    ruta_esclavo, maestro = canal_pty
    simulador = SimuladorControlador(
        ruta_puerto=ruta_esclavo,
        intervalo_latido_s=0.1,
        latencia_respuesta_s=0.05,
        modo="normal",
    )
    simulador.iniciar()
    salida = SalidaFalsa()
    persistencia = PersistenciaSqlite(str(tmp_path / "e2e.db"))
    nucleo = NucleoPuente(
        puerto=maestro,
        publicador=PublicadorEventos(salida),
        gestor=GestorComandos(EmisorTramasServidor(ContadorSecuenciaServidor(seq_inicial=0))),
        emisor=EmisorTramasServidor(ContadorSecuenciaServidor(seq_inicial=500)),
        vigilante=VigilanteLatido(umbral_ms=15_000, arranque_ms=int(time.monotonic() * 1000)),
        persistencia=persistencia,
        reloj_ms=lambda: int(time.monotonic() * MS_POR_SEGUNDO),
    )
    try:
        # 1. PING del puente y volcado de estado del simulador.
        nucleo.volcar_estado_inicial()
        nucleo.emitir_ping()
        _bombeo(nucleo, maestro, 0.4)
        latidos = [p for p in salida.publicaciones if p.topico == "portus/evt/estado"]
        assert latidos, "el simulador debió emitir al menos un latido EST"
        assert latidos[0].json()["datos"]["modo"] == "NORMAL"

        # 2. Eventos de la secuencia del simulador publicados con el envoltorio único.
        _bombeo(nucleo, maestro, 0.6)
        topicos_evt = {p.topico for p in salida.publicaciones if p.topico.startswith("portus/evt/")}
        assert "portus/evt/garita" in topicos_evt
        assert "portus/evt/pesaje" in topicos_evt

        # 3. Flujo de comando §6.4: solicitud → CMD → RSP ACK → respuesta publicada.
        solicitud = json.dumps(
            {
                "id": "cmd-e2e-1",
                "ts": "2026-09-20T14:03:22.418Z",
                "origen": "servidor",
                "tipo": "comando.solicitud",
                "seq": None,
                "datos": {
                    "cmd_id": "e2e-cmd-1",
                    "nombre": "GruaSuspender",
                    "parametros": {},
                    "usuario": "terminal",
                },
            }
        ).encode("utf-8")
        nucleo.atender_mensaje_mqtt("portus/cmd/solicitud", solicitud)
        assert _esperar_publicacion(
            nucleo, maestro, salida, lambda p: p.topico == "portus/cmd/respuesta", PLAZO_ESPERA_S
        )
        respuesta = [p for p in salida.publicaciones if p.topico == "portus/cmd/respuesta"][-1]
        datos = respuesta.json()["datos"]
        assert datos["cmd_id"] == "e2e-cmd-1"
        assert datos["estado"] == "ACK"

        # 4. Comando con condición de rechazo simulada: NAK con causa exacta.
        solicitud_nak = json.dumps(
            {
                "id": "cmd-e2e-2",
                "ts": "2026-09-20T14:03:22.418Z",
                "origen": "servidor",
                "tipo": "comando.solicitud",
                "seq": None,
                "datos": {
                    "cmd_id": "e2e-cmd-2",
                    "nombre": "AbrirTalanquera",
                    "parametros": {},
                    "usuario": "terminal",
                },
            }
        ).encode("utf-8")
        nucleo.atender_mensaje_mqtt("portus/cmd/solicitud", solicitud_nak)
        assert _esperar_publicacion(
            nucleo,
            maestro,
            salida,
            lambda p: p.topico == "portus/cmd/respuesta" and p.json()["datos"]["estado"] == "NAK",
            PLAZO_ESPERA_S,
        )
        respuesta_nak = [
            p
            for p in salida.publicaciones
            if p.topico == "portus/cmd/respuesta" and p.json()["datos"]["estado"] == "NAK"
        ][-1]
        assert respuesta_nak.json()["datos"]["causa"] == "VEH_BAJO_TALANQUERA"

        # 5. La persistencia registró el comando resuelto.
        assert persistencia.comando_resuelto("e2e-cmd-1")[0] == "ACK"
    finally:
        simulador.detener()


def test_respuesta_idempotente_ante_reintento_del_mismo_cmd_id(tmp_path, canal_pty):
    ruta_esclavo, maestro = canal_pty
    simulador = SimuladorControlador(
        ruta_puerto=ruta_esclavo,
        intervalo_latido_s=0.1,
        latencia_respuesta_s=0.01,
        modo="normal",
    )
    simulador.iniciar()
    salida = SalidaFalsa()
    nucleo = NucleoPuente(
        puerto=maestro,
        publicador=PublicadorEventos(salida),
        gestor=GestorComandos(EmisorTramasServidor(ContadorSecuenciaServidor(seq_inicial=0))),
        emisor=EmisorTramasServidor(ContadorSecuenciaServidor(seq_inicial=500)),
        vigilante=VigilanteLatido(umbral_ms=15_000, arranque_ms=int(time.monotonic() * 1000)),
        persistencia=PersistenciaSqlite(str(tmp_path / "e2e-idem.db")),
        reloj_ms=lambda: int(time.monotonic() * MS_POR_SEGUNDO),
    )
    try:
        _bombeo(nucleo, maestro, 0.2)
        contenido = {
            "id": "cmd-e2e-3",
            "ts": "2026-09-20T14:03:22.418Z",
            "origen": "servidor",
            "tipo": "comando.solicitud",
            "seq": None,
            "datos": {
                "cmd_id": "e2e-cmd-3",
                "nombre": "GruaReferenciar",
                "parametros": {},
                "usuario": "terminal",
            },
        }
        trama_json = json.dumps(contenido).encode("utf-8")
        nucleo.atender_mensaje_mqtt("portus/cmd/solicitud", trama_json)
        assert _esperar_publicacion(
            nucleo, maestro, salida, lambda p: p.topico == "portus/cmd/respuesta", PLAZO_ESPERA_S
        )
        nucleo.atender_mensaje_mqtt("portus/cmd/solicitud", trama_json)

        def hay_dos_respuestas() -> bool:
            respuestas_idem = [
                p
                for p in salida.publicaciones
                if p.topico == "portus/cmd/respuesta" and p.json()["datos"]["cmd_id"] == "e2e-cmd-3"
            ]
            return len(respuestas_idem) >= 2

        limite = time.monotonic() + PLAZO_ESPERA_S
        while time.monotonic() < limite and not hay_dos_respuestas():
            datos_pendientes = maestro.leer_disponible()
            if datos_pendientes:
                nucleo.procesar_bytes(datos_pendientes)
            time.sleep(0.02)
        respuestas = [
            p
            for p in salida.publicaciones
            if p.topico == "portus/cmd/respuesta" and p.json()["datos"]["cmd_id"] == "e2e-cmd-3"
        ]
        assert len(respuestas) == 2
        assert all(r.json()["datos"]["estado"] == "ACK" for r in respuestas)
    finally:
        simulador.detener()
