"""Estados del patio (SPECS §12.1) y política de asignación de posiciones.

El patio es lineal y apilable a dos niveles. Cada posición tiene uno de los
cinco estados exigidos; el detalle de nivel y contenedor vive en la tabla
``inventario`` (§17.1).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class EstadoPosicion(StrEnum):
    """Los cinco estados exactos del SPECS §12.1."""

    LIBRE = "libre"
    RESERVADA = "reservada"
    OCUPADA_NIVEL_1 = "ocupada nivel 1"
    OCUPADA_NIVEL_2 = "ocupada nivel 2"
    BLOQUEADA = "bloqueada"


NIVELES_PATIO = frozenset({1, 2})
PERMANENCIA_EXCESIVA_HORAS = 2
"""Umbral del indicador de permanencia y de AL13 (§12.2, §13.1)."""


@dataclass(frozen=True)
class CeldaInventario:
    """Una celda (posición, nivel) del patio con su contenedor, si hay."""

    posicion: str
    nivel: int
    contenedor_id: str | None
    remociones: int = 0
    ingreso_en: str | None = None


@dataclass(frozen=True)
class EstadoDePosicion:
    """Estado base de una posición (libre/reservada/ocupada/bloqueada, §12.1)."""

    id: str
    estado: str


class PoliticaAsignacion(Protocol):
    """Contrato §12.4 [PROP]: intercambiar políticas sin tocar el resto del código."""

    def asignar_posicion(
        self,
        contenedor_id: str,
        inventario: tuple[CeldaInventario, ...],
        posiciones: tuple[EstadoDePosicion, ...],
    ) -> tuple[str, int]:
        """Elige (posicion, nivel) para el contenedor; lanza ErrorPatio si no hay."""
        ...


class ErrorPatio(Exception):
    """No hay celda disponible para asignar (SPECS §12.4)."""
