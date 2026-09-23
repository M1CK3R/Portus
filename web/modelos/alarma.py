"""Alarmas del servidor (SPECS §13): catálogo que genera la plataforma.

El controlador reporta sus alarmas por ALM y el puente las publica; este
modelo cubre las que el **servidor** genera en la Etapa 5: AL09, AL10, AL11 y
AL14 (§13.1). AL12 y AL13 dependen de un planificador (tarea periódica) y
llegan con su etapa; AL01 la genera el puente (§5.4).
"""

from dataclasses import dataclass
from enum import StrEnum


class CodigoAlarma(StrEnum):
    """Subconjunto del catálogo §13.1 que genera la lógica del servidor."""

    AL09 = "AL09"
    AL10 = "AL10"
    AL11 = "AL11"
    AL14 = "AL14"


@dataclass(frozen=True)
class DefinicionAlarma:
    """Fila del catálogo §13.1: severidad y descripción."""

    codigo: CodigoAlarma
    severidad: str
    descripcion: str


DEFINICIONES: dict[CodigoAlarma, DefinicionAlarma] = {
    CodigoAlarma.AL09: DefinicionAlarma(CodigoAlarma.AL09, "MEDIA", "Pesaje fuera de tolerancia"),
    CodigoAlarma.AL10: DefinicionAlarma(
        CodigoAlarma.AL10, "MEDIA", "Vehículo incorrecto en la salida"
    ),
    CodigoAlarma.AL11: DefinicionAlarma(CodigoAlarma.AL11, "MEDIA", "Parqueo de retención lleno"),
    CodigoAlarma.AL14: DefinicionAlarma(
        CodigoAlarma.AL14, "BAJA", "Comando remoto rechazado por el controlador"
    ),
}


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
