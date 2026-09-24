"""Ciclo de grúa registrado (SPECS §12.6: datos del ciclo para métricas y gráfica).

Cada ciclo es el trabajo de grúa que el controlador confirma (``FIN OK``) o
aborta (``ABORTO``); de aquí salen las métricas 1-3 de §16.1 y la gráfica de
tiempos de ciclo de la pestaña Grúa (§12.6).

Distancia de traslación (A16 [DEC]): la trama ``GRU`` no informa distancia
(docs/protocolo_serial.md §2), así que el servidor la deriva del plan en
**posiciones** del patio lineal: la zona de transferencia (el vehículo) es la
posición 0 junto a P1, y P1…Pn las siguientes en orden. Un ciclo suma la
aproximación en vacío desde donde terminó el ciclo anterior hasta el origen
y, si se completó, el traslado cargado del origen al destino; un ciclo
abortado cuenta solo la aproximación.
"""

from dataclasses import dataclass
from enum import StrEnum

from web.modelos.trabajos import ORIGEN_VEHICULO, TipoTrabajo

UNIDAD_DISTANCIA = "posiciones"
"""Unidad rotulada de la métrica 3 (A16): paso entre dos posiciones adyacentes."""
INDICE_ZONA_TRANSFERENCIA = 0
"""Extremo del patio lineal donde se para el vehículo; también la posición tras referenciar."""
SEPARADOR_NIVEL = "/"


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


def indice_de_extremo(extremo: str | None, posiciones: tuple[str, ...]) -> int:
    """Lugar en el patio lineal de un extremo de trabajo (``VEH`` o ``P2/N1``).

    Sin extremo conocido (primer ciclo tras arrancar) la grúa está en la zona
    de transferencia; una posición fuera del catálogo también cae ahí [DEC].
    """
    if extremo is None or extremo == ORIGEN_VEHICULO:
        return INDICE_ZONA_TRANSFERENCIA
    posicion = extremo.split(SEPARADOR_NIVEL)[0]
    if posicion not in posiciones:
        return INDICE_ZONA_TRANSFERENCIA
    return posiciones.index(posicion) + 1


def distancia_de_ciclo(
    desde: str | None,
    origen: str,
    destino: str,
    resultado: ResultadoCiclo,
    posiciones: tuple[str, ...],
) -> int:
    """Posiciones recorridas en un ciclo: aproximación + traslado si se completó (A16)."""
    inicio = indice_de_extremo(desde, posiciones)
    indice_origen = indice_de_extremo(origen, posiciones)
    aproximacion = abs(indice_origen - inicio)
    if resultado is ResultadoCiclo.ABORTADO:
        return aproximacion
    return aproximacion + abs(indice_de_extremo(destino, posiciones) - indice_origen)


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
