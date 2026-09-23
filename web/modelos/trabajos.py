"""Trabajos de grúa (SPECS §12.5.1): tipos, estados y reglas de cola."""

from dataclasses import dataclass
from enum import StrEnum

ORIGEN_VEHICULO = "VEH"
"""Marcador del vehículo como extremo de un trabajo (origen de depósito, destino de retiro)."""


class TipoTrabajo(StrEnum):
    """Los tres tipos exactos del SPECS §12.5.1."""

    DEPOSITO = "DEPOSITO"
    RETIRO = "RETIRO"
    REMOCION = "REMOCION"


class EstadoTrabajo(StrEnum):
    """Ciclo de vida de un trabajo (SPECS §12.5.1)."""

    PENDIENTE = "PENDIENTE"
    EN_CURSO = "EN_CURSO"
    COMPLETADO = "COMPLETADO"
    ABORTADO = "ABORTADO"


@dataclass(frozen=True)
class Trabajo:
    """Un trabajo de grúa en la cola del turno (SPECS §12.5.1)."""

    id: int
    turno_id: int
    tipo: TipoTrabajo
    contenedor_id: str
    origen: str
    destino: str
    nivel: int
    estado: EstadoTrabajo
    orden: int
    creado_en: str = ""
