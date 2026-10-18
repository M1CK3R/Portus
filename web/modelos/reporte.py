"""Reporte de corrida (SPECS §16.3): etiqueta, rango, 8 métricas y política activa.

Cada reporte generado se persiste (§16.3 [PROP]) para poder recuperarlo y
compararlo con la Fase 3; los CSV de exportación llevan el detalle de cada
turno del periodo y el resumen de métricas, ambos con la política activa
(§12.4, §16.3).

Rango: el formulario envía fecha y hora **de la terminal** sin zona
(``datetime-local``); se interpreta en UTC-6 y se guarda en UTC como todas las
marcas del sistema (CODESTYLE I-8, BD-5). Compararlo tal cual contra las
marcas UTC desplazaba el periodo 6 horas.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from web.modelos.ciclo_grua import UNIDAD_DISTANCIA
from web.modelos.cita import ZONA_LOCAL
from web.tiempo import marca_utc


@dataclass(frozen=True)
class Reporte:
    """Un reporte generado con sus 8 métricas (SPECS §16.1, §16.3)."""

    id: int
    etiqueta: str
    inicio: str
    fin: str
    politica: str
    resultado: dict[str, object]
    generado_por: int | None
    generado_en: str


# Nombres exactos de las 8 métricas de §16.1; se usan en el JSON del reporte y
# en las pruebas de serie conocida (§16.2). El orden es el de la tabla [REQ].
METRICAS: tuple[str, ...] = (
    "remociones_por_contenedor_retirado",
    "ciclos_grua_por_operacion",
    "distancia_total_recorrida",
    "tiempo_promedio_camion_terminal_min",
    "tiempo_promedio_retencion_min",
    "longitud_maxima_fila_espera",
    "porcentaje_citas_cumplidas_en_ventana",
    "retenciones_por_causa_y_resolucion",
)

UNIDADES: dict[str, str] = {
    METRICAS[0]: "remociones por retiro",
    METRICAS[1]: "ciclos por turno cerrado",
    METRICAS[2]: UNIDAD_DISTANCIA,
    METRICAS[3]: "min",
    METRICAS[4]: "min",
    METRICAS[5]: "vehículos",
    METRICAS[6]: "%",
    METRICAS[7]: "retenciones",
}
"""Rótulo de cada métrica (A16: distancia en posiciones del patio lineal)."""

CLAVE_UNIDADES = "unidades"
"""El JSON del reporte lleva las 8 métricas y sus rótulos bajo esta clave."""

LARGO_MAXIMO_ETIQUETA = 80


class ErrorRango(ValueError):
    """Rango del reporte ilegible o invertido (se responde 422)."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


def normalizar_rango(inicio: str, fin: str) -> tuple[str, str]:
    """(inicio, fin) en marcas UTC; sin zona se leen en hora de la terminal (UTC-6).

    Acepta el valor de ``datetime-local`` (``2026-09-24T08:00``) y cualquier
    marca ISO 8601 con zona (``…Z`` o ``-06:00``). Exige inicio < fin.
    """
    desde = _instante(inicio)
    hasta = _instante(fin)
    if desde >= hasta:
        raise ErrorRango("RANGO_INVERTIDO", "El inicio del rango debe ser anterior al fin.")
    return (marca_utc(desde.astimezone(UTC)), marca_utc(hasta.astimezone(UTC)))


def _instante(texto: str) -> datetime:
    try:
        instante = datetime.fromisoformat(texto.strip().replace("Z", "+00:00"))
    except ValueError as error:
        mensaje = f"'{texto}' no es una fecha y hora válida (aaaa-mm-ddTHH:MM)"
        raise ErrorRango("RANGO_INVALIDO", mensaje) from error
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=ZONA_LOCAL)
    return instante
