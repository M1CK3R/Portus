"""Catálogo de alarmas AL01-AL14 (SPECS §13.1) y su ciclo de vida (§13.2).

Fuente única de código, severidad, descripción y origen (CODESTYLE N-7); la
paridad con ``docs/constantes_protocolo.json`` (lo que el firmware reporta en
``ALM``) la verifica ``pruebas/test_paridad_constantes.py``. Una alarma no
desaparece al cesar su condición: sigue activa hasta que TERMINAL la reconoce.
"""

from dataclasses import dataclass
from enum import StrEnum


class CodigoAlarma(StrEnum):
    """Los 14 códigos exactos del SPECS §13.1."""

    AL01 = "AL01"
    AL02 = "AL02"
    AL03 = "AL03"
    AL04 = "AL04"
    AL05 = "AL05"
    AL06 = "AL06"
    AL07 = "AL07"
    AL08 = "AL08"
    AL09 = "AL09"
    AL10 = "AL10"
    AL11 = "AL11"
    AL12 = "AL12"
    AL13 = "AL13"
    AL14 = "AL14"


class Severidad(StrEnum):
    """Severidades de §13.1; CRITICA y ALTA se reconocen una por una (§13.3)."""

    CRITICA = "CRITICA"
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAJA = "BAJA"


SEVERIDADES_EN_LOTE: frozenset[Severidad] = frozenset({Severidad.MEDIA, Severidad.BAJA})
"""Las únicas que admite «Reconocer todas» (§13.3)."""

ORIGEN_SERVIDOR = "servidor"
ORIGEN_CONTROLADOR = "controlador"


@dataclass(frozen=True)
class DefinicionAlarma:
    """Fila del catálogo §13.1: severidad, descripción y quién la genera."""

    codigo: CodigoAlarma
    severidad: Severidad
    descripcion: str
    origen: str


_CATALOGO: tuple[DefinicionAlarma, ...] = (
    DefinicionAlarma(
        CodigoAlarma.AL01, Severidad.CRITICA, "Enlace con el controlador perdido", ORIGEN_SERVIDOR
    ),
    DefinicionAlarma(
        CodigoAlarma.AL02, Severidad.CRITICA, "Paro de emergencia accionado", ORIGEN_CONTROLADOR
    ),
    DefinicionAlarma(
        CodigoAlarma.AL03,
        Severidad.CRITICA,
        "Pérdida de referencia de posición de la grúa",
        ORIGEN_CONTROLADOR,
    ),
    DefinicionAlarma(
        CodigoAlarma.AL04,
        Severidad.CRITICA,
        "Pérdida de carga durante el traslado",
        ORIGEN_CONTROLADOR,
    ),
    DefinicionAlarma(
        CodigoAlarma.AL05, Severidad.ALTA, "Agarre de contenedor no confirmado", ORIGEN_CONTROLADOR
    ),
    DefinicionAlarma(
        CodigoAlarma.AL06, Severidad.ALTA, "Trabajo de grúa abortado", ORIGEN_CONTROLADOR
    ),
    DefinicionAlarma(
        CodigoAlarma.AL07,
        Severidad.ALTA,
        "Inconsistencia entre altura física e inventario",
        ORIGEN_CONTROLADOR,
    ),
    DefinicionAlarma(
        CodigoAlarma.AL08,
        Severidad.ALTA,
        "Movimiento del vehículo durante la transferencia",
        ORIGEN_CONTROLADOR,
    ),
    DefinicionAlarma(
        CodigoAlarma.AL09, Severidad.MEDIA, "Pesaje fuera de tolerancia", ORIGEN_SERVIDOR
    ),
    DefinicionAlarma(
        CodigoAlarma.AL10, Severidad.MEDIA, "Vehículo incorrecto en la salida", ORIGEN_SERVIDOR
    ),
    DefinicionAlarma(
        CodigoAlarma.AL11, Severidad.MEDIA, "Parqueo de retención lleno", ORIGEN_SERVIDOR
    ),
    DefinicionAlarma(
        CodigoAlarma.AL12, Severidad.MEDIA, "Retención que supera treinta minutos", ORIGEN_SERVIDOR
    ),
    DefinicionAlarma(
        CodigoAlarma.AL13,
        Severidad.BAJA,
        "Permanencia de contenedor superior a dos horas",
        ORIGEN_SERVIDOR,
    ),
    DefinicionAlarma(
        CodigoAlarma.AL14,
        Severidad.BAJA,
        "Comando remoto rechazado por el controlador",
        ORIGEN_SERVIDOR,
    ),
)

DEFINICIONES: dict[CodigoAlarma, DefinicionAlarma] = {d.codigo: d for d in _CATALOGO}
"""Catálogo §13.1 indexado por código; AL07 también puede originarla el servidor."""


def definicion(codigo: str) -> DefinicionAlarma | None:
    """Definición del catálogo; None si el código no es AL01-AL14 (D-10)."""
    try:
        return DEFINICIONES[CodigoAlarma(codigo)]
    except ValueError:
        return None


@dataclass(frozen=True)
class Alarma:
    """Fila de ``alarma`` del dominio (§17.1); persiste hasta reconocimiento (§13.2)."""

    id: int
    codigo: str
    severidad: str
    origen: str
    descripcion: str
    datos: dict[str, object]
    repeticiones: int
    estado: str
    ts: str
    reconocida_por: int | None = None
    reconocida_ts: str | None = None
    comentario: str | None = None
    reconocida_por_usuario: str | None = None
