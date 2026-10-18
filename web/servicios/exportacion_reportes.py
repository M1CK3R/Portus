"""CSV de un reporte de corrida (SPECS §16.3; línea base de la Fase 3).

Dos archivos por reporte, ambos con la **política de asignación** en cada fila
para poder juntar corridas de distintas políticas (§12.4, §16.3):

* ``detalle``: una fila por turno del periodo (identidad, pesos, ventana,
  ciclos y distancia de grúa, retenciones, tiempos).
* ``metricas``: el resumen con las 8 métricas y su unidad (A16).

Las marcas van en UTC ISO 8601 (BD-5) y el tiempo en terminal en minutos.
Una celda de texto libre que empiece con ``= + - @`` se antepone con ``'``
para que una hoja de cálculo no la ejecute como fórmula (S-2).
"""

import csv
import io

from web.modelos.reporte import CLAVE_UNIDADES, METRICAS, Reporte
from web.repositorios.repositorio_reportes import DetalleTurnoReporte
from web.tiempo import instante_de_marca

INICIOS_DE_FORMULA = ("=", "+", "-", "@", "\t", "\r")
SEGUNDOS_POR_MINUTO = 60.0

COLUMNAS_DETALLE: tuple[str, ...] = (
    "reporte",
    "etiqueta",
    "politica_asignacion",
    "turno",
    "vehiculo",
    "transportista",
    "contenedor",
    "tipo_op",
    "estado",
    "canal",
    "dentro_de_ventana",
    "peso_entrada_g",
    "peso_salida_g",
    "posicion_patio",
    "nivel",
    "ciclos_grua",
    "remociones",
    "distancia_grua_posiciones",
    "retenciones",
    "creado_en_utc",
    "cerrado_en_utc",
    "tiempo_terminal_min",
    "motivo_anulacion",
)

COLUMNAS_METRICAS: tuple[str, ...] = (
    "reporte",
    "etiqueta",
    "politica_asignacion",
    "desde_utc",
    "hasta_utc",
    "metrica",
    "valor",
    "unidad",
)


def csv_detalle(reporte: Reporte, filas: list[DetalleTurnoReporte]) -> str:
    """Una fila por turno del periodo del reporte (§16.3 «detalle de cada turno»)."""
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\n")
    escritor.writerow(COLUMNAS_DETALLE)
    for fila in filas:
        escritor.writerow(
            [
                reporte.id,
                _celda(reporte.etiqueta),
                reporte.politica,
                fila.turno,
                _celda(fila.vehiculo),
                _celda(fila.transportista),
                _celda(fila.contenedor),
                fila.tipo_op,
                fila.estado,
                fila.canal,
                _booleano(fila.dentro_de_ventana),
                _opcional(fila.peso_entrada_g),
                _opcional(fila.peso_salida_g),
                fila.posicion_patio,
                _opcional(fila.nivel),
                fila.ciclos_grua,
                fila.remociones,
                fila.distancia_grua,
                fila.retenciones,
                fila.creado_en,
                fila.cerrado_en,
                _minutos(fila.creado_en, fila.cerrado_en),
                _celda(fila.motivo_anulacion),
            ]
        )
    return salida.getvalue()


def csv_metricas(reporte: Reporte) -> str:
    """Resumen de la corrida: una fila por métrica (y por grupo de la métrica 8)."""
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\n")
    escritor.writerow(COLUMNAS_METRICAS)
    unidades = reporte.resultado.get(CLAVE_UNIDADES)
    rotulos = unidades if isinstance(unidades, dict) else {}
    comunes = [reporte.id, _celda(reporte.etiqueta), reporte.politica, reporte.inicio, reporte.fin]
    for metrica in METRICAS:
        valor = reporte.resultado.get(metrica)
        unidad = str(rotulos.get(metrica, ""))
        if isinstance(valor, dict):
            for grupo, cantidad in sorted(valor.items()):
                escritor.writerow([*comunes, f"{metrica}[{grupo}]", cantidad, unidad])
        else:
            escritor.writerow([*comunes, metrica, "" if valor is None else valor, unidad])
    return salida.getvalue()


def _celda(texto: str) -> str:
    """Neutraliza la inyección de fórmulas en hojas de cálculo (S-2)."""
    return f"'{texto}" if texto.startswith(INICIOS_DE_FORMULA) else texto


def _opcional(valor: int | None) -> str:
    return "" if valor is None else str(valor)


def _booleano(valor: bool | None) -> str:
    if valor is None:
        return ""
    return "si" if valor else "no"


def _minutos(creado_en: str, cerrado_en: str) -> str:
    """Tiempo en la terminal del turno cerrado, en minutos con 2 decimales."""
    if not cerrado_en:
        return ""
    try:
        segundos = (instante_de_marca(cerrado_en) - instante_de_marca(creado_en)).total_seconds()
    except ValueError:
        return ""
    return f"{max(0.0, segundos) / SEGUNDOS_POR_MINUTO:.2f}"
