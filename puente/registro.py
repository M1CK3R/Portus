"""Configuración del registro con formato uniforme en UTC (CODESTYLE D-1, D-2, I-8)."""

import logging
import sys
import time
from collections.abc import Callable

FORMATO_REGISTRO = "%(asctime)s.%(msecs)03dZ · %(levelname)s · %(name)s · %(message)s"
FORMATO_FECHA = "%Y-%m-%dT%H:%M:%S"


class FormatoUtc(logging.Formatter):
    """Renderiza la marca de tiempo del registro en UTC con formato ISO 8601."""

    converter: Callable[[float | None], time.struct_time] = time.gmtime


def configurar_registro(nivel: int) -> None:
    """Instala el formato único del proyecto; los mensajes van en español (D-2)."""
    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(FormatoUtc(FORMATO_REGISTRO, datefmt=FORMATO_FECHA))
    raiz = logging.getLogger()
    raiz.handlers.clear()
    raiz.addHandler(manejador)
    raiz.setLevel(nivel)
