"""Lectura de config/portus.env con valores por omisión (SPECS §19.2, CODESTYLE A-7)."""

import logging
from dataclasses import dataclass
from pathlib import Path

REGISTRO = logging.getLogger(__name__)

PUERTO_SERIE_POR_OMISION = "/dev/ttyUSB0"
BAUDIOS_POR_OMISION = 115200
MQTT_HOST_POR_OMISION = "127.0.0.1"
MQTT_PUERTO_POR_OMISION = 1883
MQTT_USUARIO_POR_OMISION = "portus-puente"
MQTT_CONTRASENA_POR_OMISION = "portus"
RUTA_BD_POR_OMISION = "db/portus.db"
TIEMPO_LIMITE_COMANDO_S_POR_OMISION = 2.0
PERIODO_LATIDO_S_POR_OMISION = 5.0
PERIODOS_SIN_LATIDO_POR_OMISION = 3
PERIODO_PING_S_POR_OMISION = 3.0
NIVEL_REGISTRO_POR_OMISION = "INFO"

NIVEL_POR_NOMBRE = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


@dataclass(frozen=True)
class ConfiguracionPuente:
    """Parámetros de ejecución del puente; ninguno se escribe en el código (A-7)."""

    ruta_puerto_serie: str
    baudios: int
    mqtt_host: str
    mqtt_puerto: int
    mqtt_usuario: str
    mqtt_contrasena: str
    ruta_bd: str
    tiempo_limite_comando_s: float
    periodo_latido_s: float
    periodos_sin_latido: int
    periodo_ping_s: float
    nivel_registro: str

    @property
    def umbral_latido_ms(self) -> int:
        """Umbral de tres periodos sin latido en ms (SPECS §5.4: 5 s → 15 s)."""
        return int(self.periodo_latido_s * self.periodos_sin_latido * 1000)

    @classmethod
    def por_omision(cls) -> "ConfiguracionPuente":
        return cls(
            ruta_puerto_serie=PUERTO_SERIE_POR_OMISION,
            baudios=BAUDIOS_POR_OMISION,
            mqtt_host=MQTT_HOST_POR_OMISION,
            mqtt_puerto=MQTT_PUERTO_POR_OMISION,
            mqtt_usuario=MQTT_USUARIO_POR_OMISION,
            mqtt_contrasena=MQTT_CONTRASENA_POR_OMISION,
            ruta_bd=RUTA_BD_POR_OMISION,
            tiempo_limite_comando_s=TIEMPO_LIMITE_COMANDO_S_POR_OMISION,
            periodo_latido_s=PERIODO_LATIDO_S_POR_OMISION,
            periodos_sin_latido=PERIODOS_SIN_LATIDO_POR_OMISION,
            periodo_ping_s=PERIODO_PING_S_POR_OMISION,
            nivel_registro=NIVEL_REGISTRO_POR_OMISION,
        )

    @classmethod
    def desde_env(cls, texto_env: str) -> "ConfiguracionPuente":
        """Construye la configuración desde el contenido de un archivo .env."""
        valores = _parsear_env(texto_env)
        return cls(
            ruta_puerto_serie=valores.get("PUERTO_SERIE", PUERTO_SERIE_POR_OMISION),
            baudios=_entero(valores, "BAUDIOS", BAUDIOS_POR_OMISION),
            mqtt_host=valores.get("MQTT_HOST", MQTT_HOST_POR_OMISION),
            mqtt_puerto=_entero(valores, "MQTT_PUERTO", MQTT_PUERTO_POR_OMISION),
            mqtt_usuario=valores.get("MQTT_USUARIO", MQTT_USUARIO_POR_OMISION),
            mqtt_contrasena=valores.get("MQTT_CONTRASENA", MQTT_CONTRASENA_POR_OMISION),
            ruta_bd=valores.get("RUTA_BD", RUTA_BD_POR_OMISION),
            tiempo_limite_comando_s=_flotante(
                valores, "TIEMPO_LIMITE_COMANDO_S", TIEMPO_LIMITE_COMANDO_S_POR_OMISION
            ),
            periodo_latido_s=_flotante(valores, "PERIODO_LATIDO_S", PERIODO_LATIDO_S_POR_OMISION),
            periodos_sin_latido=_entero(
                valores, "PERIODOS_SIN_LATIDO", PERIODOS_SIN_LATIDO_POR_OMISION
            ),
            periodo_ping_s=_flotante(valores, "PERIODO_PING_S", PERIODO_PING_S_POR_OMISION),
            nivel_registro=valores.get("NIVEL_REGISTRO", NIVEL_REGISTRO_POR_OMISION),
        )

    @classmethod
    def desde_archivo(cls, ruta: str) -> "ConfiguracionPuente":
        archivo = Path(ruta)
        if not archivo.is_file():
            mensaje = f"no existe el archivo de configuración '{ruta}'"
            raise FileNotFoundError(mensaje)
        return cls.desde_env(archivo.read_text(encoding="utf-8"))

    def nivel_logging(self) -> int:
        return NIVEL_POR_NOMBRE.get(self.nivel_registro.upper(), logging.INFO)


def _parsear_env(texto_env: str) -> dict[str, str]:
    valores: dict[str, str] = {}
    for linea in texto_env.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        valores[clave.strip()] = valor.strip()
    return valores


def _entero(valores: dict[str, str], clave: str, por_omision: int) -> int:
    if clave not in valores:
        return por_omision
    try:
        return int(valores[clave])
    except ValueError as error:
        raise ValueError(f"{clave} debe ser entero (recibido: '{valores[clave]}')") from error


def _flotante(valores: dict[str, str], clave: str, por_omision: float) -> float:
    if clave not in valores:
        return por_omision
    try:
        return float(valores[clave])
    except ValueError as error:
        raise ValueError(f"{clave} debe ser un número (recibido: '{valores[clave]}')") from error
