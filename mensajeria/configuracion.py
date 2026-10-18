"""Lectura de config/portus.env para portus-msg (SPECS §15.4, §19.2; CODESTYLE A-7, S-1).

El token del bot sale **solo** de ``TELEGRAM_BOT_TOKEN`` en ``portus.env``
(excluido del repositorio). El usuario MQTT es propio del servicio
(``portus-msg``, solo lectura de ``portus/srv/*`` en ``acl_portus``, S-4).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from web.configuracion.configuracion_web import (
    MQTT_HOST_POR_OMISION,
    MQTT_PUERTO_POR_OMISION,
    NIVEL_POR_NOMBRE,
    NIVEL_REGISTRO_POR_OMISION,
    RUTA_BD_POR_OMISION,
    parsear_env,
)

MSG_MQTT_USUARIO_POR_OMISION = "portus-msg"
NOMBRE_TERMINAL_POR_OMISION = "Terminal Portuaria PORTUS"
URL_API_TELEGRAM_POR_OMISION = "https://api.telegram.org/bot"


@dataclass(frozen=True)
class ConfiguracionMensajeria:
    """Parámetros de ejecución de portus-msg; ninguno vive en el código (A-7)."""

    token_bot: str = field(repr=False)
    """Secreto (S-1): ``repr=False`` para que nunca llegue a un registro."""
    ruta_bd: str = RUTA_BD_POR_OMISION
    mqtt_host: str = MQTT_HOST_POR_OMISION
    mqtt_puerto: int = MQTT_PUERTO_POR_OMISION
    mqtt_usuario: str = MSG_MQTT_USUARIO_POR_OMISION
    mqtt_contrasena: str = field(default="", repr=False)
    nombre_terminal: str = NOMBRE_TERMINAL_POR_OMISION
    url_api_telegram: str = URL_API_TELEGRAM_POR_OMISION
    """Solo se cambia para apuntar a una Bot API falsa en pruebas locales."""
    nivel_registro: str = NIVEL_REGISTRO_POR_OMISION

    @classmethod
    def desde_env(cls, texto_env: str) -> "ConfiguracionMensajeria":
        """Construye la configuración; exige el token (sin él no hay canal)."""
        valores = parsear_env(texto_env)
        token = valores.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            mensaje = (
                "falta TELEGRAM_BOT_TOKEN en portus.env: cree el bot con @BotFather "
                "(docs/mensajeria.md §1) y pegue el token"
            )
            raise ValueError(mensaje)
        puerto_texto = valores.get("MQTT_PUERTO", str(MQTT_PUERTO_POR_OMISION))
        try:
            puerto = int(puerto_texto)
        except ValueError as error:
            mensaje = f"MQTT_PUERTO debe ser entero (recibido: '{puerto_texto}')"
            raise ValueError(mensaje) from error
        return cls(
            token_bot=token,
            ruta_bd=valores.get("RUTA_BD", RUTA_BD_POR_OMISION),
            mqtt_host=valores.get("MQTT_HOST", MQTT_HOST_POR_OMISION),
            mqtt_puerto=puerto,
            mqtt_usuario=valores.get("MSG_MQTT_USUARIO", MSG_MQTT_USUARIO_POR_OMISION),
            mqtt_contrasena=valores.get("MSG_MQTT_CONTRASENA", ""),
            nombre_terminal=valores.get("NOMBRE_TERMINAL", NOMBRE_TERMINAL_POR_OMISION),
            url_api_telegram=valores.get("TELEGRAM_URL_API", URL_API_TELEGRAM_POR_OMISION),
            nivel_registro=valores.get("NIVEL_REGISTRO", NIVEL_REGISTRO_POR_OMISION),
        )

    @classmethod
    def desde_archivo(cls, ruta: str) -> "ConfiguracionMensajeria":
        archivo = Path(ruta)
        if not archivo.is_file():
            mensaje = f"no existe el archivo de configuración '{ruta}'"
            raise FileNotFoundError(mensaje)
        return cls.desde_env(archivo.read_text(encoding="utf-8"))

    def nivel_logging(self) -> int:
        return NIVEL_POR_NOMBRE.get(self.nivel_registro.upper(), logging.INFO)
