"""Ciclo de grúa registrado (SPECS §12.6: datos del ciclo para métricas y gráfica).

Cada ciclo es el trabajo de grúa que el controlador confirma (``FIN OK``) o
aborta (``ABORTO``); de aquí salen las métricas 1-3 de §16.1 y la gráfica de
tiempos de ciclo de la pestaña Grúa (§12.6).
"""

from dataclasses import dataclass
from enum import StrEnum

from web.modelos.trabajos import TipoTrabajo


class ResultadoCiclo(StrEnum):
    """Resultado exacto del ciclo (SPECS §12.6)."""

    COMPLETADO = "COMPLETADO"
    ABORTADO = "ABORTADO"


@dataclass(frozen=True)
class CicloGrua:
    """Un ciclo de grúa persistido (SPECS §12.6, §17.1)."""

    id: int
    turno_id: int
    trabajo_id: int | None
    tipo: TipoTrabajo
    ts_inicio: str
    ts_fin: str
    distancia_traslacion: int
    resultado: ResultadoCiclo
    creado_en: str


@dataclass(frozen=True)
class FallaGrua:
    """Una falla del historial de la grúa (SPECS §12.6: historial de fallas).

    Tipos posibles: pérdida de referencia, agarre no confirmado, movimiento
    abortado, pérdida de carga (AL03, AL05, AL06, AL04 respectivamente).
    """

    codigo: str
    descripcion: str
    ts: str
    datos: dict[str, object]
