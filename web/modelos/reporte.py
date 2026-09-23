"""Reporte de corrida (SPECS §16.3): etiqueta, rango, 8 métricas y política activa.

Cada reporte generado se persiste (§16.3 [PROP]) para poder recuperarlo y
compararlo con la Fase 3; el CSV de exportación lleva el detalle de cada turno
del periodo más la política activa (§12.4, §16.3).
"""

from dataclasses import dataclass


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
