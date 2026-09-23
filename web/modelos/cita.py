"""Citas, franjas y ventana de presentación (SPECS §11).

Franjas de 15 minutos con capacidad de 2 citas; la ventana válida va desde la
hora de inicio de la franja hasta 5 minutos después de la hora de fin
(§11.1 regla 6: franja 10:00-10:15 → ventana [10:00, 10:20]). Las franjas se
programan en hora local de Guatemala (UTC-6, sin horario de verano; CODESTYLE
I-8), así que la comparación de ventana se hace en esa zona fija.
"""

from datetime import datetime, timedelta, timezone
from enum import StrEnum

DURACION_FRANJA_MIN = 15
CAPACIDAD_FRANJA = 2
VENTANA_TOLERANCIA_MIN = 5

ZONA_LOCAL = timezone(timedelta(hours=-6), "Guatemala")
"""Zona fija UTC-6 de la terminal: franjas y ventanas se evalúan aquí (I-8)."""


class EstadoCita(StrEnum):
    """Estados exactos de la cita (SPECS §8.3, §11.2)."""

    PROGRAMADA = "programada"
    CUMPLIDA = "cumplida"
    VENCIDA = "vencida"
    CANCELADA = "cancelada"


def esta_dentro_de_ventana(
    fecha_franja: str, hora_inicio_franja: str, hora_fin_franja: str, ahora: datetime
) -> bool:
    """True si ``ahora`` (con zona) cae dentro de la ventana de la franja.

    La ventana abre a la hora de inicio de la franja y cierra ``fin + 5 min``
    (§11.1 regla 6); llegar antes de la hora de inicio también está fuera
    (RT04). ``hora_inicio_franja`` y ``hora_fin_franja`` vienen en ``HH:MM``
    local. Las zonas fijas permiten comparar instantes directamente (PY-5).
    """
    inicio = _instante_local(fecha_franja, hora_inicio_franja)
    limite = _instante_local(fecha_franja, hora_fin_franja) + timedelta(
        minutes=VENTANA_TOLERANCIA_MIN
    )
    return inicio <= ahora <= limite


def _instante_local(fecha: str, hora_texto: str) -> datetime:
    """Convierte ``aaaa-mm-dd`` + ``HH:MM`` locales en un datetime con zona."""
    hora, minuto = (int(parte) for parte in hora_texto.split(":"))
    anio, mes, dia = (int(parte) for parte in fecha.split("-"))
    return datetime(anio, mes, dia, hora, minuto, tzinfo=ZONA_LOCAL)
