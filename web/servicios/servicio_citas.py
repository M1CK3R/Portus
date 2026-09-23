"""Gestión de la agenda del día (SPECS §11.4, §14.5, Etapa 6).

Cancelar y reprogramar **notifican al transportista** (§11.4); bloquear franja
impide nuevas citas. El indicador de cumplimiento mide el % de citas del día
cumplidas dentro de su ventana (§14.5).
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.cita import EstadoCita
from web.repositorios.repositorio_citas import FranjaAgenda, RepositorioCitas
from web.repositorios.repositorio_notificaciones import RepositorioNotificaciones
from web.servicios.puertos import PublicadorLogica
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

TOPICO_SRV_CITA = "portus/srv/cita"


class ServicioCitas:
    """Acciones de TERMINAL sobre la agenda (§11.4, §14.5)."""

    def __init__(
        self,
        citas: RepositorioCitas,
        notificaciones: RepositorioNotificaciones,
        publicador: PublicadorLogica,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._citas = citas
        self._notificaciones = notificaciones
        self._publicador = publicador
        self._fabrica_instante = fabrica_instante

    def agenda(self, fecha: str) -> list[FranjaAgenda]:
        """Franjas del día con capacidad, bloqueo y citas asignadas (§14.5)."""
        return self._citas.agenda_de_fecha(fecha)

    def cumplimiento(self, fecha: str) -> tuple[int, int]:
        """(cumplidas_en_ventana, total) del día para el indicador (§14.5)."""
        return self._citas.cumplimiento_de_fecha(fecha)

    def cancelar(self, cita_id: int) -> bool:
        """Cancela la cita y notifica al transportista (§11.4)."""
        cita = self._citas.buscar_por_id(cita_id)
        if cita is None:
            return False
        ts = marca_utc(self._fabrica_instante())
        ok = self._citas.cancelar(cita_id, ts)
        if ok:
            self._notificar(cita.transportista_id, "cita_cancelada", {"cita": cita_id, "ts": ts})
        return ok

    def reprogramar(self, cita_id: int, fecha: str, inicio: str) -> tuple[bool, str]:
        """Reprograma la cita a otra franja con capacidad y notifica (§11.4)."""
        cita = self._citas.buscar_por_id(cita_id)
        if cita is None:
            return (False, "CITA_INEXISTENTE")
        ts = marca_utc(self._fabrica_instante())
        ok, motivo = self._citas.reprogramar(cita_id, fecha, inicio, ts)
        if ok:
            self._notificar(
                cita.transportista_id,
                "cita_reprogramada",
                {"cita": cita_id, "fecha": fecha, "inicio": inicio, "ts": ts},
            )
        return (ok, motivo)

    def bloquear_franja(self, fecha: str, inicio: str) -> bool:
        """Bloquea una franja para impedir nuevas citas (§11.4, §14.5)."""
        return self._citas.bloquear_franja(fecha, inicio)

    def _notificar(self, transportista_id: int, tipo: str, payload: dict[str, object]) -> None:
        """Persiste la notificación y la publica para el bot (Etapa 10, §15.3)."""
        self._notificaciones.crear(
            transportista_id, tipo, payload, marca_utc(self._fabrica_instante())
        )
        self._publicador.publicar(
            TOPICO_SRV_CITA,
            f"notificacion.{tipo}",
            {**payload, "transportista": transportista_id},
        )
        REGISTRO.info("Notificación %s al transportista %d", tipo, transportista_id)


def estado_de_cita(estado: str) -> EstadoCita:
    """Conversión explícita del texto de la BD al enum (§11.2)."""
    return EstadoCita(estado)
