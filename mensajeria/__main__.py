"""Punto de entrada de portus-msg: ``python -m mensajeria --config config/portus.env``.

Arma el bot sobre la base compartida (sin reaplicar el esquema: lo migra
portus-web, que arranca antes según §19.2) y corre en un solo bucle asyncio
el *long polling*, la cola de avisos, el barrido de pendientes y los
recordatorios; la escucha MQTT vive en el hilo de paho (PY-4).
"""

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from mensajeria.adaptador_telegram import (
    AplicacionTelegram,
    CanalTelegram,
    configurar_bot,
    crear_aplicacion,
)
from mensajeria.configuracion import ConfiguracionMensajeria
from mensajeria.conversaciones import LimitadorVinculacion, RegistroConversaciones
from mensajeria.despachador import DespachadorAvisos
from mensajeria.escucha_mqtt import EscuchaAvisos
from mensajeria.flujo_cita import FlujoCita
from mensajeria.modelos import CanalMensajeria
from mensajeria.recordatorios import PERIODO_REVISION_RECORDATORIOS_S, PlanificadorRecordatorios
from mensajeria.servicio_bot import DependenciasBot, ServicioBot
from puente.registro import configurar_registro
from web.repositorios.conexion_bd import ConexionBd
from web.repositorios.repositorio_citas import RepositorioCitas
from web.repositorios.repositorio_consultas_transportista import (
    RepositorioConsultasTransportista,
)
from web.repositorios.repositorio_notificaciones import RepositorioNotificaciones
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.repositorios.repositorio_vinculos import RepositorioVinculos
from web.servicios.servicio_vinculacion import ServicioVinculacion

REGISTRO = logging.getLogger(__name__)

PERIODO_BARRIDO_PENDIENTES_S = 60
"""Cada minuto se reencolan los avisos que no salieron (sin internet, §15.4)."""
REGISTROS_SILENCIADOS = ("httpx", "httpcore")
"""httpx registra cada URL de la Bot API, que lleva el token: nunca a INFO (S-1)."""
TIPOS_DE_UPDATE_ATENDIDOS = ["message", "callback_query"]
"""Solo mensajes y botones: ediciones y publicaciones de canales no se piden a Telegram."""


def instante_utc() -> datetime:
    return datetime.now(UTC)


class ServicioMensajeria:
    """Dueño de las tareas de fondo del bot y de la escucha MQTT (PY-7)."""

    def __init__(
        self,
        fabrica_despachador: Callable[[CanalMensajeria], DespachadorAvisos],
        planificador: PlanificadorRecordatorios,
        fabrica_escucha: Callable[[Callable[[int], None]], EscuchaAvisos],
    ) -> None:
        self._fabrica_despachador = fabrica_despachador
        self._planificador = planificador
        self._fabrica_escucha = fabrica_escucha
        self._despachador: DespachadorAvisos | None = None
        self._escucha: EscuchaAvisos | None = None
        self._tareas: list[asyncio.Task[None]] = []

    async def iniciar(self, aplicacion: AplicacionTelegram) -> None:
        """``post_init`` de PTB: configura el bot y lanza las tareas concurrentes."""
        await configurar_bot(aplicacion)
        despachador = self._fabrica_despachador(CanalTelegram(aplicacion))
        self._despachador = despachador
        bucle = asyncio.get_running_loop()
        self._tareas = [
            asyncio.create_task(despachador.ejecutar(), name="cola-avisos"),
            asyncio.create_task(
                _periodica("barrido-avisos", PERIODO_BARRIDO_PENDIENTES_S, self._barrer),
                name="barrido-avisos",
            ),
            asyncio.create_task(
                _periodica("recordatorios", PERIODO_REVISION_RECORDATORIOS_S, self._recordar),
                name="recordatorios",
            ),
        ]

        def al_aviso(notificacion_id: int) -> None:
            # Hilo de paho → bucle asyncio: la cola solo se toca desde el bucle.
            bucle.call_soon_threadsafe(despachador.encolar, notificacion_id)

        self._escucha = self._fabrica_escucha(al_aviso)
        self._escucha.iniciar()

    async def detener(self, aplicacion: AplicacionTelegram) -> None:
        """``post_stop`` de PTB: corta la escucha y las tareas con limpieza (PY-6)."""
        _ = aplicacion
        if self._escucha is not None:
            self._escucha.detener()
        for tarea in self._tareas:
            tarea.cancel()
        await asyncio.gather(*self._tareas, return_exceptions=True)

    async def _barrer(self) -> None:
        if self._despachador is not None:
            await self._despachador.barrer()

    async def _recordar(self) -> None:
        creadas = await asyncio.to_thread(self._planificador.revisar)
        if self._despachador is not None:
            for notificacion_id in creadas:
                self._despachador.encolar(notificacion_id)


async def _periodica(nombre: str, periodo_s: float, accion: Callable[[], Awaitable[None]]) -> None:
    """Repite la acción; un fallo de una pasada se registra y la tarea sigue (D-6)."""
    while True:
        try:
            await accion()
        except Exception:
            REGISTRO.exception("La tarea %s falló en esta pasada", nombre)
        await asyncio.sleep(periodo_s)


def _leer_argumentos() -> argparse.Namespace:
    analizador = argparse.ArgumentParser(
        prog="mensajeria",
        description="Bot de Telegram del transportista de PORTUS (SPECS §15)",
    )
    analizador.add_argument(
        "--config",
        default="config/portus.env",
        help="ruta del archivo de configuración (por omisión: config/portus.env)",
    )
    return analizador.parse_args()


def main() -> int:
    argumentos = _leer_argumentos()
    try:
        configuracion = ConfiguracionMensajeria.desde_archivo(argumentos.config)
    except (FileNotFoundError, ValueError) as error:
        sys.stderr.write(f"configuración inválida: {error}\n")
        return 2
    configurar_registro(configuracion.nivel_logging())
    # PTB 22 anuncia que ``retry_after`` pasará a timedelta; el adaptador ya lo
    # maneja, así que se adopta el comportamiento nuevo y se evita el aviso.
    os.environ.setdefault("PTB_TIMEDELTA", "1")
    for nombre in REGISTROS_SILENCIADOS:
        logging.getLogger(nombre).setLevel(logging.WARNING)
    bd = ConexionBd(configuracion.ruta_bd, aplicar_esquema=False)
    try:
        aplicacion = _armar(configuracion, bd)
        REGISTRO.info("portus-msg iniciando el long polling de Telegram")
        aplicacion.run_polling(allowed_updates=TIPOS_DE_UPDATE_ATENDIDOS)
    finally:
        bd.cerrar()
    return 0


def _armar(configuracion: ConfiguracionMensajeria, bd: ConexionBd) -> AplicacionTelegram:
    """Construye servicio, cola, planificador y aplicación (dueño único, PY-7)."""
    usuarios = RepositorioUsuarios(bd)
    vinculos = RepositorioVinculos(bd)
    citas = RepositorioCitas(bd)
    notificaciones = RepositorioNotificaciones(bd)
    conversaciones = RegistroConversaciones(instante_utc)
    servicio = ServicioBot(
        DependenciasBot(
            vinculacion=ServicioVinculacion(vinculos, usuarios, instante_utc),
            vinculos=vinculos,
            usuarios=usuarios,
            citas=citas,
            consultas=RepositorioConsultasTransportista(bd),
            flujo_cita=FlujoCita(citas, notificaciones, conversaciones, instante_utc),
            conversaciones=conversaciones,
            limitador=LimitadorVinculacion(instante_utc),
            nombre_terminal=configuracion.nombre_terminal,
            fabrica_instante=instante_utc,
        )
    )
    fondo = ServicioMensajeria(
        lambda canal: DespachadorAvisos(notificaciones, vinculos, canal, instante_utc),
        PlanificadorRecordatorios(citas, notificaciones, instante_utc),
        lambda al_aviso: EscuchaAvisos(
            configuracion.mqtt_host,
            configuracion.mqtt_puerto,
            configuracion.mqtt_usuario,
            configuracion.mqtt_contrasena,
            al_aviso,
        ),
    )
    return crear_aplicacion(
        configuracion.token_bot,
        configuracion.url_api_telegram,
        servicio,
        fondo.iniciar,
        fondo.detener,
    )


if __name__ == "__main__":
    raise SystemExit(main())
