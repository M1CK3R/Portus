"""Punto de entrada del servicio portus-puente: ``python -m puente --config ...``."""

import argparse
import signal
import sys

from puente.configuracion import ConfiguracionPuente
from puente.puente import Puente
from puente.registro import configurar_registro

NIVEL_REGISTRO_POR_OMISION = "INFO"


def _leer_argumentos() -> argparse.Namespace:
    analizador = argparse.ArgumentParser(
        prog="puente",
        description="Puente serial <-> MQTT de PORTUS Fase 2 (SPECS §4, §5, §6.4)",
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
        configuracion = ConfiguracionPuente.desde_archivo(argumentos.config)
    except (FileNotFoundError, ValueError) as error:
        sys.stderr.write(f"configuración inválida: {error}\n")
        return 2
    nivel = configuracion.nivel_logging()
    configurar_registro(nivel)
    puente = Puente(configuracion)
    for nombre_senal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(nombre_senal, lambda senal, marco: puente.detener())
    try:
        puente.ejecutar()
    finally:
        puente.apagar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
