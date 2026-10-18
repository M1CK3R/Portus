"""Frontera con la Bot API de Telegram (SPECS §15.4; CODESTYLE A-2, I-4, S-2).

Único módulo que importa ``python-telegram-bot``. Traduce cada *update* a
los modelos propios (``chat_id`` → ``id_chat``, ``callback_data`` → ``dato``),
llama al servicio fuera del bucle asyncio (``asyncio.to_thread``: el SQL no
frena el *polling*, PY-4) y convierte la :class:`Respuesta` en mensajes.

Orden de los manejadores (§15.4): primero los comandos, luego los botones y
al final un manejador genérico para **todo** lo demás, así ningún mensaje
queda sin respuesta. El manejador de errores también responde.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import timedelta
from typing import Any

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import (
    BadRequest,
    ChatMigrated,
    Forbidden,
    NetworkError,
    RetryAfter,
    TelegramError,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from mensajeria.modelos import (
    ErrorLimiteCanal,
    ErrorPermanenteCanal,
    ErrorRedCanal,
    MensajeEntrante,
    PulsacionBoton,
    Respuesta,
)
from mensajeria.servicio_bot import ServicioBot
from mensajeria.textos import COMANDO_START, COMANDOS, TEXTO_ERROR_INTERNO, TEXTO_SOLO_PRIVADO

REGISTRO = logging.getLogger(__name__)

AplicacionTelegram = Application[Any, Any, Any, Any, Any, Any]
"""Los seis parámetros de tipo de ``Application`` son internos de PTB; en esta
frontera con la librería se admite ``Any`` (PY-1)."""
Contexto = ContextTypes.DEFAULT_TYPE
GanchoCiclo = Callable[[AplicacionTelegram], Coroutine[Any, Any, None]]


def segundos_de_espera(valor: int | timedelta) -> float:
    """``retry_after`` llega como entero o ``timedelta`` según la versión de PTB."""
    return valor.total_seconds() if isinstance(valor, timedelta) else float(valor)


class CanalTelegram:
    """Implementa ``CanalMensajeria`` con ``sendMessage`` en texto plano (§15.4)."""

    def __init__(self, aplicacion: AplicacionTelegram) -> None:
        self._aplicacion = aplicacion

    async def enviar(self, id_chat: int, texto: str) -> None:
        """Traduce los errores de Telegram a los del canal (límite, red, permanente)."""
        try:
            await self._aplicacion.bot.send_message(chat_id=id_chat, text=texto)
        except RetryAfter as error:
            raise ErrorLimiteCanal(segundos_de_espera(error.retry_after)) from error
        except (Forbidden, BadRequest, ChatMigrated) as error:
            raise ErrorPermanenteCanal(str(error)) from error
        except NetworkError as error:
            raise ErrorRedCanal(str(error)) from error
        except TelegramError as error:
            raise ErrorPermanenteCanal(str(error)) from error


def crear_aplicacion(
    token: str,
    url_api: str,
    servicio: ServicioBot,
    al_iniciar: GanchoCiclo,
    al_detener: GanchoCiclo,
) -> AplicacionTelegram:
    """Arma la aplicación de PTB con los manejadores en el orden de §15.4."""
    aplicacion: AplicacionTelegram = (
        ApplicationBuilder()
        .token(token)
        .base_url(url_api)
        .post_init(al_iniciar)
        .post_stop(al_detener)
        .build()
    )
    solo_mensajes = filters.UpdateType.MESSAGE
    nombres = [nombre for nombre, _ in COMANDOS] + [COMANDO_START]

    async def manejar_mensaje(update: Update, contexto: Contexto) -> None:
        chat, mensaje = update.effective_chat, update.effective_message
        if chat is None or mensaje is None:
            return
        if chat.type != ChatType.PRIVATE:
            await contexto.bot.send_message(chat_id=chat.id, text=TEXTO_SOLO_PRIVADO)
            return
        entrada = MensajeEntrante(id_chat=chat.id, texto=mensaje.text or "")
        respuesta = await asyncio.to_thread(servicio.atender_mensaje, entrada)
        await _responder(contexto, chat.id, respuesta)

    async def manejar_boton(update: Update, contexto: Contexto) -> None:
        consulta, chat = update.callback_query, update.effective_chat
        if consulta is None or chat is None:
            return
        await consulta.answer()  # answerCallbackQuery: quita el «cargando» del botón
        dato = consulta.data if isinstance(consulta.data, str) else ""
        pulsacion = PulsacionBoton(id_chat=chat.id, dato=dato)
        respuesta = await asyncio.to_thread(servicio.atender_pulsacion, pulsacion)
        try:
            # Evita la doble pulsación: el teclado ya usado desaparece.
            await consulta.edit_message_reply_markup(reply_markup=None)
        except BadRequest:
            REGISTRO.debug("El teclado ya no se podía editar; se continúa")
        await _responder(contexto, chat.id, respuesta)

    aplicacion.add_handler(CommandHandler(nombres, manejar_mensaje, filters=solo_mensajes))
    aplicacion.add_handler(CallbackQueryHandler(manejar_boton))
    aplicacion.add_handler(MessageHandler(solo_mensajes, manejar_mensaje))
    aplicacion.add_error_handler(_manejar_error)
    return aplicacion


async def configurar_bot(aplicacion: AplicacionTelegram) -> None:
    """Long polling sin webhook y menú de los 7 comandos (§15.4 pasos 2 y «Recepción»)."""
    await aplicacion.bot.delete_webhook(drop_pending_updates=False)
    await aplicacion.bot.set_my_commands(
        [BotCommand(nombre, descripcion) for nombre, descripcion in COMANDOS]
    )
    REGISTRO.info("Bot @%s listo: webhook eliminado y menú registrado", aplicacion.bot.username)


async def _responder(contexto: Contexto, id_chat: int, respuesta: Respuesta) -> None:
    teclado = None
    if respuesta.botones:
        teclado = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(boton.texto, callback_data=boton.dato) for boton in fila]
                for fila in respuesta.botones
            ]
        )
    await contexto.bot.send_message(chat_id=id_chat, text=respuesta.texto, reply_markup=teclado)


async def _manejar_error(update: object, contexto: Contexto) -> None:
    """Registra el fallo con traza y, si hay chat, responde igual (§15.2 «nunca sin respuesta»).

    Un corte de red durante el *polling* no es un fallo del bot: PTB reintenta
    solo y aquí basta una línea de advertencia (sin traza repetida en cada ciclo).
    """
    error = contexto.error
    if isinstance(error, NetworkError) and not isinstance(error, BadRequest):
        REGISTRO.warning("Sin conexión con la Bot API de Telegram: %s", error)
        return
    REGISTRO.error("Fallo atendiendo un update de Telegram", exc_info=error)
    if not isinstance(update, Update) or update.effective_chat is None:
        return
    try:
        await contexto.bot.send_message(chat_id=update.effective_chat.id, text=TEXTO_ERROR_INTERNO)
    except TelegramError:
        REGISTRO.warning("Tampoco se pudo avisar del fallo al chat %d", update.effective_chat.id)
