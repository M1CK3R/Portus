"""Agenda de citas del servidor (SPECS §11, §14.5; Etapas 6 y 11).

* TERMINAL cancela y reprograma (notifican al transportista, aviso 7 de §15.3,
  con el contenedor y, si se reprogramó, la ventana nueva) y bloquea franjas.
  Una cita que ya respaldó el ingreso de un vehículo no se toca: su desenlace
  lo decide el turno (A11). Reprogramar solo va hacia una franja futura.
* Tarea periódica: la cita programada que pasa ``fin + 5 min`` sin que el
  vehículo se presente queda ``vencida`` con la ventana incumplida (§11.2).
* Indicador de cumplimiento del día (§14.5).
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.cita import (
    EstadoCita,
    fecha_local,
    fin_de_franja,
    franja_valida,
    instante_local,
    ventana_cerrada,
)
from web.modelos.notificacion import TipoNotificacion
from web.repositorios.repositorio_ciclo_cita import RepositorioCicloCita
from web.repositorios.repositorio_citas import CitaConFranja, FranjaAgenda, RepositorioCitas
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.servicios.notificador import Notificador
from web.servicios.puertos import PublicadorLogica

REGISTRO = logging.getLogger(__name__)

TOPICO_SRV_CITA = "portus/srv/cita"
TIPO_CITA_VENCIDA = "cita.vencida"

MOTIVO_CITA_INEXISTENTE = "CITA_INEXISTENTE"
MOTIVO_CITA_EN_USO = "CITA_EN_USO"
MOTIVO_CITA_NO_PROGRAMADA = "CITA_NO_PROGRAMADA"
MOTIVO_FRANJA_INVALIDA = "FRANJA_INVALIDA"
MOTIVO_FRANJA_PASADA = "FRANJA_PASADA"


class ServicioCitas:
    """Acciones de TERMINAL sobre la agenda y vencimiento de citas (§11.2, §11.4)."""

    def __init__(
        self,
        citas: RepositorioCitas,
        ciclo: RepositorioCicloCita,
        manifiestos: RepositorioManifiestos,
        notificador: Notificador,
        publicador: PublicadorLogica,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._citas = citas
        self._ciclo = ciclo
        self._manifiestos = manifiestos
        self._notificador = notificador
        self._publicador = publicador
        self._fabrica_instante = fabrica_instante

    def agenda(self, fecha: str) -> list[FranjaAgenda]:
        """Franjas del día con capacidad, bloqueo y citas asignadas (§14.5)."""
        return self._citas.agenda_de_fecha(fecha)

    def cumplimiento(self, fecha: str) -> tuple[int, int]:
        """(cumplidas_en_ventana, total) del día para el indicador (§14.5)."""
        return self._citas.cumplimiento_de_fecha(fecha)

    def cancelar(self, cita_id: int) -> tuple[bool, str]:
        """Cancela una cita programada y notifica al transportista (§11.4)."""
        cita = self._citas.buscar_por_id(cita_id)
        if cita is None:
            return (False, MOTIVO_CITA_INEXISTENTE)
        if self._ciclo.en_uso(cita_id):
            return (False, MOTIVO_CITA_EN_USO)
        if not self._citas.cancelar(cita_id):
            return (False, MOTIVO_CITA_NO_PROGRAMADA)
        self._notificar(
            cita,
            TipoNotificacion.CITA_CANCELADA,
            {"fecha": cita.franja_fecha, "inicio": cita.franja_inicio, "fin": cita.franja_fin},
        )
        return (True, "")

    def reprogramar(self, cita_id: int, fecha: str, inicio: str) -> tuple[bool, str]:
        """Mueve la cita a una franja futura con capacidad y notifica la ventana nueva (§11.4)."""
        if not franja_valida(fecha, inicio):
            return (False, MOTIVO_FRANJA_INVALIDA)
        if instante_local(fecha, inicio) <= self._fabrica_instante():
            return (False, MOTIVO_FRANJA_PASADA)
        cita = self._citas.buscar_por_id(cita_id)
        if cita is None:
            return (False, MOTIVO_CITA_INEXISTENTE)
        if self._ciclo.en_uso(cita_id):
            return (False, MOTIVO_CITA_EN_USO)
        ok, motivo = self._citas.reprogramar(cita_id, fecha, inicio)
        if ok:
            self._notificar(
                cita,
                TipoNotificacion.CITA_REPROGRAMADA,
                {"fecha": fecha, "inicio": inicio, "fin": fin_de_franja(inicio)},
            )
        return (ok, motivo)

    def bloquear_franja(self, fecha: str, inicio: str) -> bool:
        """Bloquea una franja (exista o no todavía) para impedir nuevas citas (§11.4)."""
        if not franja_valida(fecha, inicio):
            return False
        return self._citas.bloquear_franja(fecha, inicio)

    def vencer_no_atendidas(self) -> list[int]:
        """Tarea periódica: ``programada → vencida`` al cerrar la ventana sin presentarse.

        Devuelve los ids vencidos en esta pasada; cada uno se publica en
        ``portus/srv/cita`` para que el tablero lo refleje (no es uno de los 9
        avisos al transportista; ``/miscitas`` ya muestra el estado).
        """
        ahora = self._fabrica_instante()
        vencidas: list[int] = []
        for cita in self._ciclo.vencibles(fecha_local(ahora)):
            if not ventana_cerrada(cita.fecha, cita.fin, ahora):
                continue
            if not self._ciclo.marcar_vencida(cita.id):
                continue
            vencidas.append(cita.id)
            self._publicador.publicar(
                TOPICO_SRV_CITA,
                TIPO_CITA_VENCIDA,
                {
                    "cita": cita.id,
                    "contenedor": cita.contenedor_id,
                    "fecha": cita.fecha,
                    "inicio": cita.inicio,
                    "fin": cita.fin,
                },
            )
            REGISTRO.info(
                "Cita %d vencida: %s %s-%s sin presentarse",
                cita.id,
                cita.fecha,
                cita.inicio,
                cita.fin,
            )
        return vencidas

    def _notificar(
        self, cita: CitaConFranja, tipo: TipoNotificacion, ventana: dict[str, object]
    ) -> None:
        """Aviso 7 al transportista de la cita con su contenedor (§15.3)."""
        manifiesto = self._manifiestos.buscar_por_id(cita.manifiesto_id)
        payload: dict[str, object] = {
            "cita": cita.id,
            "contenedor": manifiesto.contenedor_id if manifiesto is not None else "",
            **ventana,
        }
        self._notificador.notificar(TOPICO_SRV_CITA, cita.transportista_id, tipo, payload)


def estado_de_cita(estado: str) -> EstadoCita:
    """Conversión explícita del texto de la BD al enum (§11.2)."""
    return EstadoCita(estado)
