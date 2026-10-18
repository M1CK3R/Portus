"""Declaración de mercancías del AGENTE (SPECS §9.3, §14.8, Etapa 7).

Formulario con número único, régimen, descripción ≥ 10 caracteres y valor > 0;
se presenta sobre un manifiesto y habilita la solicitud de levante ante la
AUTORIDAD (§9.1).
"""

from dataclasses import dataclass
from enum import StrEnum


class Regimen(StrEnum):
    """Regímenes exactos del SPECS §9.3."""

    IMPORTACION_DEFINITIVA = "IMPORTACION_DEFINITIVA"
    DEPOSITO_TEMPORAL = "DEPOSITO_TEMPORAL"


@dataclass(frozen=True)
class Declaracion:
    """Una declaración de mercancías presentada por un AGENTE (§9.3, §17.1)."""

    id: int
    manifiesto_id: int
    agente_id: int
    numero: str
    regimen: Regimen
    descripcion: str
    valor: int
    presentada_en: str


@dataclass(frozen=True)
class SolicitudLevante:
    """Solicitud de levante vista por la AUTORIDAD (§14.9, §9.1).

    Trae la identidad del manifiesto, contenedor, naviera, agente, declaración
    y peso declarado para la bandeja de Solicitudes de levante.
    """

    levante_id: int
    manifiesto_id: int
    contenedor_id: str
    naviera: str
    agente: str
    numero_declaracion: str
    peso_declarado_g: int
    estado: str
