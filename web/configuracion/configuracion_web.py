"""Lectura de config/portus.env con valores por omisión (SPECS §19.2, CODESTYLE A-7).

El analizador es un espejo deliberado del del puente
(``puente.configuracion._parsear_env``): ocho líneas que si un día crecen se
extraen a un módulo común; hasta entonces, duplicarlas es más barato que
acoplar dos servicios independientes.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

REGISTRO = logging.getLogger(__name__)

RUTA_BD_POR_OMISION = "db/portus.db"
RUTA_ESQUEMA_POR_OMISION = str(Path(__file__).resolve().parent.parent.parent / "db" / "esquema.sql")
WEB_PUERTO_POR_OMISION = 8000
WEB_EXPIRACION_INACTIVIDAD_MIN_POR_OMISION = 30
WEB_CLAVE_SECRETA_POR_OMISION = "solo-desarrollo-cambiar-en-portus-env"
WEB_VIDA_MAXIMA_SESION_H_POR_OMISION = 12
NIVEL_REGISTRO_POR_OMISION = "INFO"

NIVEL_POR_NOMBRE = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


@dataclass(frozen=True)
class ConfiguracionWeb:
    """Parámetros de ejecución de portus-web; ninguno vive en el código (A-7)."""

    ruta_bd: str
    ruta_esquema: str
    clave_secreta: str
    puerto_web: int
    expiracion_inactividad_min: int
    vida_maxima_sesion_h: int
    nivel_registro: str

    @property
    def expiracion_inactividad_s(self) -> float:
        """Umbral de inactividad en segundos (§7.3: expiración por inactividad)."""
        return self.expiracion_inactividad_min * 60

    @property
    def vida_maxima_sesion_s(self) -> float:
        """Tope absoluto de la cookie firmada, con sesión activa o no (§7.3)."""
        return self.vida_maxima_sesion_h * 3600

    @property
    def clave_de_desarrollo(self) -> bool:
        """True si sigue la clave de ejemplo: hay que definirla en portus.env (S-1)."""
        return self.clave_secreta == WEB_CLAVE_SECRETA_POR_OMISION

    @classmethod
    def por_omision(cls) -> "ConfiguracionWeb":
        return cls(
            ruta_bd=RUTA_BD_POR_OMISION,
            ruta_esquema=RUTA_ESQUEMA_POR_OMISION,
            clave_secreta=WEB_CLAVE_SECRETA_POR_OMISION,
            puerto_web=WEB_PUERTO_POR_OMISION,
            expiracion_inactividad_min=WEB_EXPIRACION_INACTIVIDAD_MIN_POR_OMISION,
            vida_maxima_sesion_h=WEB_VIDA_MAXIMA_SESION_H_POR_OMISION,
            nivel_registro=NIVEL_REGISTRO_POR_OMISION,
        )

    @classmethod
    def desde_env(cls, texto_env: str) -> "ConfiguracionWeb":
        """Construye la configuración desde el contenido de un archivo .env."""
        valores = _parsear_env(texto_env)
        return cls(
            ruta_bd=valores.get("RUTA_BD", RUTA_BD_POR_OMISION),
            ruta_esquema=valores.get("RUTA_ESQUEMA", RUTA_ESQUEMA_POR_OMISION),
            clave_secreta=valores.get("WEB_CLAVE_SECRETA", WEB_CLAVE_SECRETA_POR_OMISION),
            puerto_web=_entero(valores, "WEB_PUERTO", WEB_PUERTO_POR_OMISION),
            expiracion_inactividad_min=_entero(
                valores,
                "WEB_EXPIRACION_INACTIVIDAD_MIN",
                WEB_EXPIRACION_INACTIVIDAD_MIN_POR_OMISION,
            ),
            vida_maxima_sesion_h=_entero(
                valores, "WEB_VIDA_MAXIMA_SESION_H", WEB_VIDA_MAXIMA_SESION_H_POR_OMISION
            ),
            nivel_registro=valores.get("NIVEL_REGISTRO", NIVEL_REGISTRO_POR_OMISION),
        )

    @classmethod
    def desde_archivo(cls, ruta: str) -> "ConfiguracionWeb":
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
