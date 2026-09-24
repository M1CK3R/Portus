"""Citas, franjas y ventana de presentación (SPECS §11).

Franjas de 15 minutos con capacidad de 2 citas; la ventana válida va desde la
hora de inicio de la franja hasta 5 minutos después de la hora de fin
(§11.1 regla 6: franja 10:00-10:15 → ventana [10:00, 10:20]). Las franjas se
programan en hora local de Guatemala (UTC-6, sin horario de verano; CODESTYLE
I-8), así que la comparación de ventana se hace en esa zona fija.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

DURACION_FRANJA_MIN = 15
CAPACIDAD_FRANJA = 2
VENTANA_TOLERANCIA_MIN = 5
FRANJAS_OFRECIDAS = 4
"""Cuántas franjas con capacidad ofrece ``/cita`` (§11.3 paso 3: «próximas N, p. ej. 4»)."""
HORIZONTE_OFRECIMIENTO_FRANJAS = 96
"""Franjas revisadas al ofrecer: 24 h hacia adelante (§11.3 paso 2)."""

ZONA_LOCAL = timezone(timedelta(hours=-6), "Guatemala")
"""Zona fija UTC-6 de la terminal: franjas y ventanas se evalúan aquí (I-8)."""

FORMATO_FECHA = "%Y-%m-%d"
FORMATO_HORA = "%H:%M"


class EstadoCita(StrEnum):
    """Estados exactos de la cita (SPECS §8.3, §11.2)."""

    PROGRAMADA = "programada"
    CUMPLIDA = "cumplida"
    VENCIDA = "vencida"
    CANCELADA = "cancelada"


@dataclass(frozen=True)
class OcupacionFranja:
    """Lo que la BD sabe de una franja: bloqueo y citas programadas (§11.1)."""

    bloqueada: bool
    asignadas: int


@dataclass(frozen=True)
class FranjaOfrecida:
    """Franja con capacidad que ``/cita`` ofrece, en hora local (§11.3)."""

    fecha: str
    inicio: str
    fin: str


def esta_dentro_de_ventana(
    fecha_franja: str, hora_inicio_franja: str, hora_fin_franja: str, ahora: datetime
) -> bool:
    """True si ``ahora`` (con zona) cae dentro de la ventana de la franja.

    La ventana abre a la hora de inicio de la franja y cierra ``fin + 5 min``
    (§11.1 regla 6); llegar antes de la hora de inicio también está fuera
    (RT04). ``hora_inicio_franja`` y ``hora_fin_franja`` vienen en ``HH:MM``
    local. Las zonas fijas permiten comparar instantes directamente (PY-5).
    """
    inicio = instante_local(fecha_franja, hora_inicio_franja)
    limite = instante_local(fecha_franja, hora_fin_franja) + timedelta(
        minutes=VENTANA_TOLERANCIA_MIN
    )
    return inicio <= ahora <= limite


def ventana_cerrada(fecha_franja: str, hora_fin_franja: str, ahora: datetime) -> bool:
    """True si ya pasó ``fin + 5 min``: la cita no atendida pasa a ``vencida`` (§11.2)."""
    limite = instante_local(fecha_franja, hora_fin_franja) + timedelta(
        minutes=VENTANA_TOLERANCIA_MIN
    )
    return ahora > limite


def franja_valida(fecha: str, inicio: str) -> bool:
    """``aaaa-mm-dd`` real y ``HH:MM`` alineado a 15 min (§11.1 regla 1); valida entradas."""
    try:
        instante = datetime.strptime(
            f"{fecha} {inicio}", f"{FORMATO_FECHA} {FORMATO_HORA}"
        ).replace(tzinfo=ZONA_LOCAL)
    except ValueError:
        return False
    return (
        instante.strftime(FORMATO_FECHA) == fecha
        and instante.strftime(FORMATO_HORA) == inicio
        and instante.minute % DURACION_FRANJA_MIN == 0
    )


def fecha_local(ahora: datetime) -> str:
    """Fecha de la terminal (UTC-6) de un instante con zona (I-8)."""
    return ahora.astimezone(ZONA_LOCAL).strftime(FORMATO_FECHA)


def fin_de_franja(inicio: str) -> str:
    """Fin de la franja: inicio + 15 minutos en formato HH:MM (§11.1 regla 1)."""
    return _sumar_minutos(inicio, DURACION_FRANJA_MIN)


def cierre_de_ventana(fin: str) -> str:
    """Última hora válida de presentación: fin de franja + 5 min (§11.1 regla 6)."""
    return _sumar_minutos(fin, VENTANA_TOLERANCIA_MIN)


def franjas_ofrecibles(
    ahora: datetime,
    ocupacion: Mapping[tuple[str, str], OcupacionFranja],
    cantidad: int = FRANJAS_OFRECIDAS,
) -> list[FranjaOfrecida]:
    """Las próximas ``cantidad`` franjas con capacidad desde ``ahora`` (§11.3).

    Empieza en el siguiente límite de franja (la hora actual redondeada hacia
    arriba), descarta las bloqueadas y las que ya tienen 2 citas (§11.1
    regla 5) y revisa como máximo 24 h. Una franja que no está en
    ``ocupacion`` todavía no existe en la BD: está libre.
    """
    candidata = _siguiente_limite(ahora.astimezone(ZONA_LOCAL))
    ofrecidas: list[FranjaOfrecida] = []
    for _ in range(HORIZONTE_OFRECIMIENTO_FRANJAS):
        fecha = candidata.strftime(FORMATO_FECHA)
        inicio = candidata.strftime(FORMATO_HORA)
        estado = ocupacion.get((fecha, inicio))
        if estado is None or (not estado.bloqueada and estado.asignadas < CAPACIDAD_FRANJA):
            ofrecidas.append(FranjaOfrecida(fecha, inicio, fin_de_franja(inicio)))
            if len(ofrecidas) == cantidad:
                break
        candidata += timedelta(minutes=DURACION_FRANJA_MIN)
    return ofrecidas


def fechas_de_ofrecimiento(ahora: datetime) -> list[str]:
    """Fechas locales que cubre el horizonte de ofrecimiento (hoy y mañana)."""
    local = ahora.astimezone(ZONA_LOCAL)
    return [local.strftime(FORMATO_FECHA), (local + timedelta(days=1)).strftime(FORMATO_FECHA)]


def instante_local(fecha: str, hora_texto: str) -> datetime:
    """Convierte ``aaaa-mm-dd`` + ``HH:MM`` locales en un datetime con zona."""
    hora, minuto = (int(parte) for parte in hora_texto.split(":"))
    anio, mes, dia = (int(parte) for parte in fecha.split("-"))
    return datetime(anio, mes, dia, hora, minuto, tzinfo=ZONA_LOCAL)


def _siguiente_limite(local: datetime) -> datetime:
    """Redondea hacia arriba al próximo múltiplo de 15 min (el exacto se conserva)."""
    base = local.replace(second=0, microsecond=0)
    if base < local:
        base += timedelta(minutes=1)
    resto = base.minute % DURACION_FRANJA_MIN
    if resto:
        base += timedelta(minutes=DURACION_FRANJA_MIN - resto)
    return base


def _sumar_minutos(hora_texto: str, minutos: int) -> str:
    hora, minuto = (int(parte) for parte in hora_texto.split(":"))
    total = hora * 60 + minuto + minutos
    return f"{total // 60:02d}:{total % 60:02d}"
