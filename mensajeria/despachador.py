"""Cola de envío de las notificaciones por el canal externo (SPECS §15.3, §15.4).

* **Fuente de verdad:** la fila de ``notificacion``. La cola solo guarda ids;
  lo que se envía se relee de la BD, así un aviso duplicado por el broker
  (QoS 1) o por el barrido sale una sola vez: se omite si ya está
  ``entregado`` y un id no entra dos veces a la cola (P-4).
* **Ritmo:** ≥ 1 s entre mensajes al mismo chat y ~30 por segundo en total;
  ante un 429 se espera exactamente ``retry_after`` y se reintenta, sin
  bucles de reintento inmediato.
* **Sin internet:** el fallo de red se registra sin gastar reintentos y el
  aviso queda pendiente; el barrido periódico lo vuelve a encolar cuando la
  conexión regresa. Un rechazo permanente (chat bloqueado) gasta un
  reintento y al tercero se deja de intentar.

Las lecturas y escrituras de SQLite van en ``asyncio.to_thread`` para no
detener el *polling* de Telegram mientras la web tiene el candado (PY-4).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum

from mensajeria.modelos import (
    CanalMensajeria,
    ErrorLimiteCanal,
    ErrorPermanenteCanal,
    ErrorRedCanal,
)
from mensajeria.redactor import redactar
from web.repositorios.repositorio_notificaciones import RepositorioNotificaciones
from web.repositorios.repositorio_vinculos import RepositorioVinculos
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

MAX_REINTENTOS_PERMANENTES = 3
INTERVALO_MINIMO_POR_CHAT_S = 1.0
INTERVALO_MINIMO_GLOBAL_S = 1 / 30
PAUSA_TRAS_FALLO_DE_RED_S = 5.0
"""Sin red, el siguiente envío espera un poco: la cola no martilla la conexión caída."""
LOTE_BARRIDO = 50


class ResultadoEntrega(StrEnum):
    ENTREGADA = "entregada"
    OMITIDA = "omitida"
    """Ya entregada, inexistente o sin cuenta vinculada: nada que enviar."""
    PENDIENTE_RED = "pendiente_red"
    RECHAZADA = "rechazada"


class DespachadorAvisos:
    """Entrega las notificaciones al chat del transportista propietario (§15.3)."""

    def __init__(
        self,
        notificaciones: RepositorioNotificaciones,
        vinculos: RepositorioVinculos,
        canal: CanalMensajeria,
        fabrica_instante: Callable[[], datetime],
        reloj_monotonico: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._notificaciones = notificaciones
        self._vinculos = vinculos
        self._canal = canal
        self._fabrica_instante = fabrica_instante
        self._reloj = reloj_monotonico
        self._dormir = dormir
        self._cola: asyncio.Queue[int] = asyncio.Queue()
        self._en_cola: set[int] = set()
        self._ultimo_por_chat: dict[int, float] = {}
        self._ultimo_global: float | None = None

    def encolar(self, notificacion_id: int) -> None:
        """Agrega el aviso una sola vez; se llama desde el hilo del bucle asyncio."""
        if notificacion_id in self._en_cola:
            return
        self._en_cola.add(notificacion_id)
        self._cola.put_nowait(notificacion_id)

    async def barrer(self) -> int:
        """Encola los pendientes entregables (reenvío al volver la conexión, §15.4)."""
        ids = await asyncio.to_thread(
            self._notificaciones.por_entregar, MAX_REINTENTOS_PERMANENTES, LOTE_BARRIDO
        )
        for notificacion_id in ids:
            self.encolar(notificacion_id)
        return len(ids)

    async def ejecutar(self) -> None:
        """Trabajador único de la cola; un fallo inesperado no lo detiene (P-5)."""
        while True:
            notificacion_id = await self._cola.get()
            resultado = ResultadoEntrega.OMITIDA
            try:
                resultado = await self.entregar(notificacion_id)
            except Exception:
                REGISTRO.exception(
                    "Fallo inesperado entregando la notificación %d", notificacion_id
                )
            finally:
                self._en_cola.discard(notificacion_id)
                self._cola.task_done()
            if resultado is ResultadoEntrega.PENDIENTE_RED:
                await self._dormir(PAUSA_TRAS_FALLO_DE_RED_S)

    async def entregar(self, notificacion_id: int) -> ResultadoEntrega:
        """Un intento completo de entrega de un aviso (lo usa el trabajador y las pruebas)."""
        notificacion = await asyncio.to_thread(self._notificaciones.buscar_por_id, notificacion_id)
        if notificacion is None or notificacion.entregado:
            return ResultadoEntrega.OMITIDA
        id_chat = await asyncio.to_thread(
            self._vinculos.chat_de_transportista, notificacion.transportista_id
        )
        if id_chat is None:
            return ResultadoEntrega.OMITIDA
        texto = redactar(notificacion.tipo, notificacion.payload)
        resultado = await self._enviar_respetando_limites(notificacion_id, id_chat, texto)
        if resultado is ResultadoEntrega.ENTREGADA:
            await asyncio.to_thread(
                self._notificaciones.marcar_entregada,
                notificacion_id,
                marca_utc(self._fabrica_instante()),
            )
            REGISTRO.info(
                "Notificación %d (%s) entregada al transportista %d",
                notificacion_id,
                notificacion.tipo,
                notificacion.transportista_id,
            )
        return resultado

    async def _enviar_respetando_limites(
        self, notificacion_id: int, id_chat: int, texto: str
    ) -> ResultadoEntrega:
        while True:
            await self._esperar_turno(id_chat)
            try:
                await self._canal.enviar(id_chat, texto)
            except ErrorLimiteCanal as error:
                REGISTRO.warning(
                    "Telegram pidió esperar %.0f s (notificación %d)",
                    error.espera_s,
                    notificacion_id,
                )
                await self._dormir(error.espera_s)
                continue
            except ErrorRedCanal as error:
                await self._registrar_fallo(notificacion_id, error, cuenta_reintento=False)
                return ResultadoEntrega.PENDIENTE_RED
            except ErrorPermanenteCanal as error:
                await self._registrar_fallo(notificacion_id, error, cuenta_reintento=True)
                return ResultadoEntrega.RECHAZADA
            return ResultadoEntrega.ENTREGADA

    async def _esperar_turno(self, id_chat: int) -> None:
        """Espacia los envíos: 1 s por chat y 1/30 s global (§15.4 «Límites»)."""
        ahora = self._reloj()
        espera = 0.0
        ultimo_chat = self._ultimo_por_chat.get(id_chat)
        if ultimo_chat is not None:
            espera = max(espera, ultimo_chat + INTERVALO_MINIMO_POR_CHAT_S - ahora)
        if self._ultimo_global is not None:
            espera = max(espera, self._ultimo_global + INTERVALO_MINIMO_GLOBAL_S - ahora)
        if espera > 0:
            await self._dormir(espera)
        instante = self._reloj()
        self._ultimo_por_chat[id_chat] = instante
        self._ultimo_global = instante

    async def _registrar_fallo(
        self, notificacion_id: int, error: Exception, cuenta_reintento: bool
    ) -> None:
        REGISTRO.warning(
            "No se entregó la notificación %d (%s): %s",
            notificacion_id,
            "rechazo permanente" if cuenta_reintento else "sin conexión, queda pendiente",
            error,
        )
        await asyncio.to_thread(
            self._notificaciones.registrar_fallo, notificacion_id, str(error), cuenta_reintento
        )
