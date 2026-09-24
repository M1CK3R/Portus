"""Recordatorio automático una hora antes de la ventana (SPECS §11.5, §15.3 aviso 4).

Tarea periódica del bot: busca citas ``programada`` cuya franja empieza
dentro de la próxima hora y que aún no tienen recordatorio, crea la
notificación y la marca en ``recordatorio_cita`` (una por cita y ventana;
reprogramar borra la marca). Una cita pedida con menos de una hora de
anticipación recibe el recordatorio en la primera pasada [DEC,
docs/mensajeria.md]: así el aviso 4 siempre ocurre y se puede demostrar.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from web.modelos.cita import fechas_de_ofrecimiento, instante_local
from web.modelos.notificacion import TipoNotificacion
from web.repositorios.repositorio_citas import CitaPorRecordar, RepositorioCitas
from web.repositorios.repositorio_notificaciones import RepositorioNotificaciones
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

ANTICIPACION_RECORDATORIO_MIN = 60
PERIODO_REVISION_RECORDATORIOS_S = 30
"""El aviso sale a lo sumo 30 s después de cumplirse la hora previa."""


class PlanificadorRecordatorios:
    """Genera los recordatorios pendientes; el despachador los entrega."""

    def __init__(
        self,
        citas: RepositorioCitas,
        notificaciones: RepositorioNotificaciones,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._citas = citas
        self._notificaciones = notificaciones
        self._fabrica_instante = fabrica_instante

    def revisar(self) -> list[int]:
        """Una pasada: devuelve los ids de las notificaciones creadas."""
        ahora = self._fabrica_instante()
        creadas: list[int] = []
        for cita in self._citas.por_recordar(fechas_de_ofrecimiento(ahora)):
            if not _toca_recordar(cita, ahora):
                continue
            ts = marca_utc(ahora)
            payload: dict[str, object] = {
                "cita": cita.id,
                "contenedor": cita.contenedor_id,
                "fecha": cita.fecha,
                "inicio": cita.inicio,
                "fin": cita.fin,
            }
            notificacion_id = self._notificaciones.crear(
                cita.transportista_id, TipoNotificacion.RECORDATORIO_CITA.value, payload, ts
            )
            self._citas.registrar_recordatorio(cita.id, notificacion_id, ts)
            creadas.append(notificacion_id)
            REGISTRO.info("Recordatorio de la cita %d creado (%d)", cita.id, notificacion_id)
        return creadas


def _toca_recordar(cita: CitaPorRecordar, ahora: datetime) -> bool:
    """True dentro de la hora previa al inicio de la franja (antes de que abra)."""
    inicio = instante_local(cita.fecha, cita.inicio)
    return inicio - timedelta(minutes=ANTICIPACION_RECORDATORIO_MIN) <= ahora < inicio
