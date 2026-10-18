"""AL12: retención abierta que supera treinta minutos (SPECS §10.5, §13.1).

Lógica pura con reloj inyectable (T-3): la tarea periódica del proceso web
llama a :meth:`revisar` y las pruebas la llaman con un reloj falso. Cada
retención genera AL12 **una sola vez** (tabla ``alerta_emitida``), aunque la
web se reinicie; varias retenciones excedidas a la vez acumulan repeticiones
sobre la misma alarma activa (§13.4 [DEC], docs/alarmas.md).
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from web.modelos.alarma import CodigoAlarma
from web.modelos.retencion import Retencion
from web.repositorios.repositorio_alarmas import RepositorioAlarmas
from web.repositorios.repositorio_retenciones import RepositorioRetenciones
from web.servicios.emisor_alarmas import EmisorAlarmas
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

LIMITE_RETENCION_MIN = 30
"""Umbral de AL12 (§13.1: «retención que supera treinta minutos»)."""


class VigilanteRetenciones:
    """Genera AL12 por cada retención abierta más antigua que el umbral."""

    def __init__(
        self,
        retenciones: RepositorioRetenciones,
        alarmas: RepositorioAlarmas,
        emisor: EmisorAlarmas,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._retenciones = retenciones
        self._alarmas = alarmas
        self._emisor = emisor
        self._fabrica_instante = fabrica_instante

    def revisar(self) -> list[int]:
        """Emite AL12 para las retenciones excedidas aún sin alerta; devuelve sus ids."""
        ahora = self._fabrica_instante()
        limite = marca_utc(ahora - timedelta(minutes=LIMITE_RETENCION_MIN))
        alertadas: list[int] = []
        for retencion in self._retenciones.abiertas_sin_alerta(limite):
            self._alarmar(retencion, marca_utc(ahora))
            alertadas.append(retencion.id)
        return alertadas

    def _alarmar(self, retencion: Retencion, ts: str) -> None:
        datos: dict[str, object] = {
            "retencion": retencion.id,
            "turno": retencion.turno_id,
            "causa": retencion.causa.value,
            "plaza": retencion.plaza,
            "creada_en": retencion.creada_en,
            "limite_min": LIMITE_RETENCION_MIN,
        }
        alarma_id = self._emisor.emitir(CodigoAlarma.AL12, datos, ts)
        self._alarmas.registrar_alerta(CodigoAlarma.AL12.value, str(retencion.id), alarma_id, ts)
        REGISTRO.warning(
            "AL12: retención %d (turno %d, %s) abierta desde %s supera %d min",
            retencion.id,
            retencion.turno_id,
            retencion.causa.value,
            retencion.creada_en,
            LIMITE_RETENCION_MIN,
        )
