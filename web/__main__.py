"""Punto de entrada del servicio portus-web: ``python -m web --config ...``.

Sirve la aplicación con waitress (WSGI de producción, hilos concurrentes sin
bloqueo cruzado, PY-4) y, en el mismo proceso, consume los eventos del
controlador por MQTT para la lógica del turno (Etapa 5, SPECS §19.2: la web
es el servicio que ejecuta el carril Aplicación).
"""

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta

from waitress import serve

from puente.registro import configurar_registro
from web.aplicacion import crear_aplicacion
from web.configuracion.configuracion_web import ConfiguracionWeb
from web.mqtt.cliente_logica import ClienteLogica
from web.mqtt.publicador_logica import PublicadorLogicaWeb
from web.planificador import TareaPeriodica
from web.repositorios.conexion_bd import ConexionBd
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

HILOS_WAITRESS = 8
"""Hilos concurrentes: suficiente para los cinco roles de la demostración."""
PERIODO_REVISION_RETENCIONES_S = 15
"""AL12 sale a lo sumo 15 s después de cumplirse los 30 min de retención (§13.1)."""
PERIODO_REVISION_PERMANENCIA_S = 60
"""AL13 sale a lo sumo 1 min después de cumplirse las 2 h de permanencia (§13.1)."""
PERIODO_VENCIMIENTO_CITAS_S = 60
"""Una cita no atendida queda vencida a lo sumo 1 min después de cerrar su ventana (§11.2)."""
VENTANA_RECONCILIACION_ALARMAS_H = 24
"""Al arrancar se reinyectan las alarmas guardadas por el puente en este lapso."""


def _leer_argumentos() -> argparse.Namespace:
    analizador = argparse.ArgumentParser(
        prog="web",
        description="Núcleo web de PORTUS Fase 2: sesión, permisos, lógica del turno e interfaz",
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
    cliente = ClienteLogica(
        host=configuracion.mqtt_host,
        puerto=configuracion.mqtt_puerto,
        usuario=configuracion.mqtt_usuario,
        contrasena=configuracion.mqtt_contrasena,
    )
    tareas: list[TareaPeriodica] = []
    try:
        aplicacion = crear_aplicacion(
            configuracion, bd, publicador_logica=PublicadorLogicaWeb(cliente)
        )
        # El cliente ya conoce el núcleo creado dentro de la aplicación (PY-7).
        nucleo = aplicacion.extensions["contexto_portus"].nucleo
        # E14: alarmas (AL01 retroactiva, ALM) que el puente guardó con la web
        # caída; antes de escuchar en vivo para no competir con el hilo MQTT.
        desde = datetime.now(UTC) - timedelta(hours=VENTANA_RECONCILIACION_ALARMAS_H)
        nucleo.reconciliar_alarmas(marca_utc(desde))
        cliente.vincular(nucleo)
        cliente.iniciar()
        tareas.append(
            TareaPeriodica(
                "vigilante-retenciones",
                PERIODO_REVISION_RETENCIONES_S,
                nucleo.vigilante_retenciones.revisar,
            )
        )
        tareas.append(
            TareaPeriodica(
                "vigilante-permanencia",
                PERIODO_REVISION_PERMANENCIA_S,
                nucleo.vigilante_permanencia.revisar,
            )
        )
        tareas.append(
            TareaPeriodica(
                "vencimiento-citas",
                PERIODO_VENCIMIENTO_CITAS_S,
                nucleo.citas_svc.vencer_no_atendidas,
            )
        )
        for tarea in tareas:
            tarea.iniciar()
        REGISTRO.info(
            "portus-web escuchando en http://0.0.0.0:%d/ (lógica del turno activa)",
            configuracion.puerto_web,
        )
        serve(aplicacion, host="0.0.0.0", port=configuracion.puerto_web, threads=HILOS_WAITRESS)
    finally:
        for tarea in tareas:
            tarea.detener()
        cliente.detener()
        bd.cerrar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
