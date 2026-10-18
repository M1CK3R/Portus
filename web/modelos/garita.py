"""Causas de rechazo de garita y resultado de la validación (SPECS §9.4, §4.4)."""

from dataclasses import dataclass
from enum import StrEnum


class CausaRechazoGarita(StrEnum):
    """Las seis causas exactas del SPECS §9.4; el controlador las muestra en la pantalla."""

    VEHICULO_DESCONOCIDO = "VEHICULO_DESCONOCIDO"
    SIN_MANIFIESTO = "SIN_MANIFIESTO"
    SIN_LEVANTE = "SIN_LEVANTE"
    LEVANTE_RETENIDO = "LEVANTE_RETENIDO"
    SIN_CITA = "SIN_CITA"
    PARQUEO_LLENO = "PARQUEO_LLENO"


class ResultadoAutorizacion(StrEnum):
    """Valores exactos de AUT.resultado (SPECS §4.4)."""

    AUTORIZADO = "AUTORIZADO"
    RECHAZADO = "RECHAZADO"


@dataclass(frozen=True)
class DecisionGarita:
    """Resultado de validar una identificación en garita (§9.4).

    Un rechazo no crea turno pero el servicio registra el intento con la
    causa (§8.2 regla 1); el autorizado lleva los datos que AUT envía al
    controlador y los identificadores creados en el servidor.
    """

    resultado: ResultadoAutorizacion
    causa: CausaRechazoGarita | None = None
    turno_id: int | None = None
    identificador_vehiculo: str = ""
    tipo_op: str = ""
    peso_declarado_g: int | None = None
    tolerancia_pct: int | None = None
    canal: str = ""
    posicion_asignada: str | None = None
    nivel_asignado: int | None = None
    retener_al_ingreso: bool = False
    """True con riesgo de retención y plaza disponible: RT04 nace en garita (§9.4)."""
    manifiesto_id: int | None = None
    cita_id: int | None = None
