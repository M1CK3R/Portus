"""Máquina de estados del turno (SPECS §8.1): 10 estados exactos y reglas.

Los nombres de estado se copian tal cual los fija el SPECS (CODESTYLE N-7) y
viven aquí una sola vez. El mapa de regreso de ``Retenido`` aplica la
propuesta de §8.5 (A2): el estado previo se guarda en el turno y al resolver
con Aclarar o Corregir se regresa según el mapa.
"""

from dataclasses import dataclass
from enum import StrEnum


class EstadoTurno(StrEnum):
    """Los 10 estados exactos del SPECS §8.1; ninguno más."""

    PROGRAMADO = "Programado"
    EN_GARITA = "EnGarita"
    EN_PESAJE_ENTRADA = "EnPesajeEntrada"
    EN_RUTA = "EnRuta"
    EN_TRANSFERENCIA = "EnTransferencia"
    EN_PESAJE_SALIDA = "EnPesajeSalida"
    EN_SALIDA = "EnSalida"
    RETENIDO = "Retenido"
    CERRADO = "Cerrado"
    ANULADO = "Anulado"


ESTADOS_FINALES: frozenset[EstadoTurno] = frozenset({EstadoTurno.CERRADO, EstadoTurno.ANULADO})
"""Únicos estados de cierre; ningún turno queda abierto si el vehículo salió (§8.2 regla 5)."""

TRANSICIONES_PERMITIDAS: dict[EstadoTurno, frozenset[EstadoTurno]] = {
    EstadoTurno.PROGRAMADO: frozenset({EstadoTurno.EN_GARITA, EstadoTurno.ANULADO}),
    EstadoTurno.EN_GARITA: frozenset(
        {EstadoTurno.EN_PESAJE_ENTRADA, EstadoTurno.RETENIDO, EstadoTurno.ANULADO}
    ),
    EstadoTurno.EN_PESAJE_ENTRADA: frozenset(
        {EstadoTurno.EN_RUTA, EstadoTurno.RETENIDO, EstadoTurno.ANULADO}
    ),
    EstadoTurno.EN_RUTA: frozenset({EstadoTurno.EN_TRANSFERENCIA, EstadoTurno.ANULADO}),
    # El aborto vuelve sobre el mismo estado (tras aborto, §8.1).
    EstadoTurno.EN_TRANSFERENCIA: frozenset(
        {
            EstadoTurno.EN_PESAJE_SALIDA,
            EstadoTurno.EN_TRANSFERENCIA,
            EstadoTurno.ANULADO,
        }
    ),
    EstadoTurno.EN_PESAJE_SALIDA: frozenset(
        {EstadoTurno.EN_SALIDA, EstadoTurno.RETENIDO, EstadoTurno.ANULADO}
    ),
    # §8.1 no define EnSalida -> Anulado: el turno en salida se cierra o se
    # retiene; la anulación con vehículo en puerta se resuelve con Rechazar
    # de una retención (§10.3) que sí admite Retenido -> Anulado.
    EstadoTurno.EN_SALIDA: frozenset({EstadoTurno.CERRADO, EstadoTurno.RETENIDO}),
    # §8.5/A2: la retención nacida en EnGarita (RT04) regresa a EnGarita
    # para continuar hacia el pesaje de entrada (el siguiente PES dispara
    # EnGarita → EnPesajeEntrada → EnRuta); las de EnPesajeEntrada/
    # EnPesajeSalida van a EnRuta/EnSalida (el vehículo ya cruzó la plataforma
    # y no puede volver a pisarla). La tabla §8.1 lista solo EnRuta | EnSalida;
    # el destino EnGarita se añade aquí como parte del mapa de regreso [DEC A2].
    EstadoTurno.RETENIDO: frozenset(
        {
            EstadoTurno.EN_GARITA,
            EstadoTurno.EN_RUTA,
            EstadoTurno.EN_SALIDA,
            EstadoTurno.ANULADO,
        }
    ),
    EstadoTurno.CERRADO: frozenset(),
    EstadoTurno.ANULADO: frozenset(),
}


def transicion_valida(actual: "EstadoTurno | str", nuevo: "EstadoTurno | str") -> bool:
    """True si §8.1 permite pasar de ``actual`` a ``nuevo``."""
    return EstadoTurno(nuevo) in TRANSICIONES_PERMITIDAS[EstadoTurno(actual)]


def estado_de_regreso(estado_previo: str) -> EstadoTurno:
    """Estado al que vuelve un turno retenido tras Aclarar o Corregir (A2, §8.5).

    Mapa de regreso [DEC]: la retención nacida en ``EnGarita`` (RT04) regresa a
    ``EnGarita`` para continuar hacia el pesaje de entrada (el siguiente PES
    dispara ``EnGarita → EnPesajeEntrada → EnRuta``); la de ``EnPesajeEntrada``
    (RT01/RT03) regresa a ``EnRuta`` y la de ``EnPesajeSalida`` (RT02) a
    ``EnSalida`` porque el vehículo ya cruzó la plataforma (no puede volver a
    pisarla); en cualquier otro estado se regresa al previo tal cual, que es
    lo que ``Retenido → EnGarita | EnRuta | EnSalida`` resume en la tabla.
    """
    previo = EstadoTurno(estado_previo)
    match previo:
        case EstadoTurno.EN_PESAJE_ENTRADA:
            return EstadoTurno.EN_RUTA
        case EstadoTurno.EN_PESAJE_SALIDA:
            return EstadoTurno.EN_SALIDA
        case _:
            return previo


@dataclass(frozen=True)
class Turno:
    """Fila de ``turno`` del dominio (PY-2); pesos en gramos (N-2)."""

    id: int
    vehiculo_id: int
    manifiesto_id: int
    cita_id: int | None
    tipo_op: str
    estado: EstadoTurno
    estado_previo_retencion: str | None = None
    posicion_patio: str | None = None
    nivel: int | None = None
    peso_entrada_g: int | None = None
    peso_salida_g: int | None = None
    canal: str = ""
    dentro_de_ventana: bool | None = None
    creado_en: str = ""
    cerrado_en: str | None = None
    motivo_anulacion: str | None = None


@dataclass(frozen=True)
class EventoLineaTiempo:
    """Una entrada de la línea de tiempo del turno (SPECS §14.2)."""

    id: int
    turno_id: int
    ts: str
    origen: str
    tipo: str
    descripcion: str
    valores: dict[str, object]
    seq: int | None
