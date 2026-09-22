"""Punto de entrada del servicio portus-web: ``python -m web --config ...``.

Sirve la aplicación con waitress (WSGI de producción, hilos concurrentes sin
bloqueo cruzado, PY-4): el servidor de desarrollo de Flask no es apto para
el despliegue en el SBC (SPECS §19.2).
"""

import argparse
import logging
import sys

from waitress import serve

from puente.registro import configurar_registro
from web.aplicacion import crear_aplicacion
from web.configuracion.configuracion_web import ConfiguracionWeb
from web.repositorios.conexion_bd import ConexionBd

REGISTRO = logging.getLogger(__name__)

HILOS_WAITRESS = 8
"""Hilos concurrentes: suficiente para los cinco roles de la demostración."""


def _leer_argumentos() -> argparse.Namespace:
    analizador = argparse.ArgumentParser(
        prog="web",
        description="Núcleo web de PORTUS Fase 2: sesión, permisos e interfaz (Etapa 4)",
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
        configuracion = ConfiguracionWeb.desde_archivo(argumentos.config)
    except (FileNotFoundError, ValueError) as error:
        sys.stderr.write(f"configuración inválida: {error}\n")
        return 2
    configurar_registro(configuracion.nivel_logging())
    if configuracion.clave_de_desarrollo:
        # S-1: la clave firma la cookie de sesión; debe salir de portus.env.
        logging.getLogger(__name__).warning(
            "WEB_CLAVE_SECRETA no definida en %s: se usa la clave de desarrollo; "
            "defínala antes de un despliegue real",
            argumentos.config,
        )
    bd = ConexionBd(configuracion.ruta_bd, configuracion.ruta_esquema)
    try:
        aplicacion = crear_aplicacion(configuracion, bd)
        REGISTRO.info(
            "portus-web escuchando en http://0.0.0.0:%d/",
            configuracion.puerto_web,
        )
        serve(aplicacion, host="0.0.0.0", port=configuracion.puerto_web, threads=HILOS_WAITRESS)
    finally:
        bd.cerrar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
