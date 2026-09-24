"""Reportes de corrida (SPECS §16.1, §16.3; Etapas 6 y 12): las 8 métricas.

El rango llega en hora de la terminal y se normaliza a UTC antes de consultar
(``normalizar_rango``). Cada reporte se guarda con su política de asignación
activa (§12.4) para compararlo en la Fase 3; los CSV salen de
``exportacion_reportes``. Definición de cada métrica sobre el periodo:

1. Remociones **completadas** ÷ retiros cerrados.
2. Ciclos de grúa completados ÷ turnos cerrados.
3. Suma de la distancia de traslación de los ciclos, en posiciones (A16).
4. Promedio creación → cierre de los turnos cerrados, en minutos.
5. Promedio generación → resolución de las retenciones resueltas, en minutos.
6. Máximo de vehículos en espera según el latido del controlador (A15).
7. % de citas con ventana cumplida sobre las que tienen resultado (docs/citas.md).
8. Retenciones resueltas por ``causa/resolución``.
"""

from collections.abc import Callable
from datetime import datetime

from web.modelos.ciclo_grua import ResultadoCiclo
from web.modelos.cita import fecha_local, instante_local
from web.modelos.reporte import (
    CLAVE_UNIDADES,
    LARGO_MAXIMO_ETIQUETA,
    METRICAS,
    UNIDADES,
    Reporte,
    normalizar_rango,
)
from web.modelos.trabajos import TipoTrabajo
from web.repositorios.repositorio_ciclo_cita import RepositorioCicloCita
from web.repositorios.repositorio_reportes import DetalleTurnoReporte, RepositorioReportes
from web.repositorios.repositorio_retenciones import RepositorioRetenciones
from web.repositorios.repositorio_telemetria import RepositorioTelemetria
from web.repositorios.repositorio_trabajos import RepositorioTrabajos
from web.repositorios.repositorio_turnos import RepositorioTurnos
from web.tiempo import instante_de_marca, marca_utc

ETIQUETA_POR_OMISION = "corrida"
REPORTES_LISTADOS = 20
"""Cuántos reportes guardados muestra la pestaña para recuperarlos (§16.3 [PROP])."""
DECIMALES_RAZON = 4
DECIMALES_MINUTOS = 2
SEGUNDOS_POR_MINUTO = 60.0
PORCENTAJE = 100


class ServicioReportes:
    """Genera, persiste y recupera los reportes de corrida con las 8 métricas (§16)."""

    def __init__(
        self,
        turnos: RepositorioTurnos,
        retenciones: RepositorioRetenciones,
        trabajos: RepositorioTrabajos,
        ciclo_citas: RepositorioCicloCita,
        telemetria: RepositorioTelemetria,
        reportes: RepositorioReportes,
        politica: str,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._turnos = turnos
        self._retenciones = retenciones
        self._trabajos = trabajos
        self._ciclo_citas = ciclo_citas
        self._telemetria = telemetria
        self._reportes = reportes
        self._politica = politica
        self._fabrica_instante = fabrica_instante

    def generar(self, etiqueta: str, inicio: str, fin: str, generado_por: int | None) -> Reporte:
        """Calcula y guarda el reporte del rango; eleva ``ErrorRango`` si el rango no sirve."""
        desde, hasta = normalizar_rango(inicio, fin)
        resultado = self._calcular_metricas(desde, hasta)
        reporte_id = self._reportes.registrar(
            etiqueta=etiqueta.strip()[:LARGO_MAXIMO_ETIQUETA] or ETIQUETA_POR_OMISION,
            inicio=desde,
            fin=hasta,
            politica=self._politica,
            resultado=resultado,
            generado_por=generado_por,
            generado_en=marca_utc(self._fabrica_instante()),
        )
        reporte = self._reportes.buscar_por_id(reporte_id)
        if reporte is None:  # defensa: acaba de insertarse (D-5)
            mensaje = f"el reporte {reporte_id} no se encontró tras registrarlo"
            raise RuntimeError(mensaje)
        return reporte

    def recientes(self) -> list[Reporte]:
        """Reportes guardados para recuperarlos y compararlos (§16.3 [PROP])."""
        return self._reportes.recientes(REPORTES_LISTADOS)

    def buscar(self, reporte_id: int) -> Reporte | None:
        return self._reportes.buscar_por_id(reporte_id)

    def detalle_de_turnos(self, reporte: Reporte) -> list[DetalleTurnoReporte]:
        """Turnos del periodo del reporte para el CSV de detalle (§16.3)."""
        return self._reportes.detalle_de_turnos(reporte.inicio, reporte.fin)

    def _calcular_metricas(self, inicio: str, fin: str) -> dict[str, object]:
        """Las 8 métricas de §16.1 en el orden de la tabla, con sus rótulos (A16)."""
        cerrados = self._turnos.cerrados_en_rango(inicio, fin)
        ciclos = self._trabajos.ciclos_en_rango(inicio, fin)
        retenciones = self._retenciones.resueltas_en_rango(inicio, fin)
        completados = [c for c in ciclos if c.resultado is ResultadoCiclo.COMPLETADO]

        remociones = sum(1 for c in completados if c.tipo is TipoTrabajo.REMOCION)
        retiros_cerrados = sum(1 for _, _, tipo in cerrados if tipo == TipoTrabajo.RETIRO.value)
        tiempos_camion = [_duracion_min(creado, cerrado) for creado, cerrado, _ in cerrados]
        tiempos_retencion = [_duracion_min(r[2], r[3]) for r in retenciones]
        cumplidas, total_citas = self._cumplimiento_de_citas(inicio, fin)
        por_causa_resolucion: dict[str, int] = {}
        for causa, resolucion, _, _ in retenciones:
            clave = f"{causa}/{resolucion}"
            por_causa_resolucion[clave] = por_causa_resolucion.get(clave, 0) + 1

        return {
            METRICAS[0]: round(_razon(remociones, retiros_cerrados), DECIMALES_RAZON),
            METRICAS[1]: round(_razon(len(completados), len(cerrados)), DECIMALES_RAZON),
            METRICAS[2]: sum(c.distancia_traslacion for c in ciclos),
            METRICAS[3]: round(_promedio(tiempos_camion), DECIMALES_MINUTOS),
            METRICAS[4]: round(_promedio(tiempos_retencion), DECIMALES_MINUTOS),
            METRICAS[5]: self._telemetria.max_fila_espera_en_rango(inicio, fin),
            METRICAS[6]: round(_razon(cumplidas * PORCENTAJE, total_citas), DECIMALES_MINUTOS),
            METRICAS[7]: por_causa_resolucion,
            CLAVE_UNIDADES: dict(UNIDADES),
        }

    def _cumplimiento_de_citas(self, inicio: str, fin: str) -> tuple[int, int]:
        """Métrica 7: citas cuya franja empieza en el periodo y con ventana registrada.

        La franja está en hora local y el rango en UTC: se comparan instantes
        con zona (PY-5). Cuentan las que se presentaron (dentro o fuera) y las
        vencidas; las canceladas antes de llegar no tienen resultado (§11.1
        regla 8).
        """
        desde, hasta = instante_de_marca(inicio), instante_de_marca(fin)
        filas = self._ciclo_citas.ventanas_registradas(fecha_local(desde), fecha_local(hasta))
        en_rango = [f for f in filas if desde <= instante_local(f.fecha, f.inicio) <= hasta]
        return (sum(1 for f in en_rango if f.cumplida_en_ventana), len(en_rango))


def _razon(numerador: float, denominador: int) -> float:
    return numerador / denominador if denominador else 0.0


def _promedio(valores: list[float]) -> float:
    return sum(valores) / len(valores) if valores else 0.0


def _duracion_min(inicio_iso: str, fin_iso: str) -> float:
    """Minutos entre dos marcas UTC; 0 si alguna no se puede leer (D-5)."""
    try:
        desde = instante_de_marca(inicio_iso)
        hasta = instante_de_marca(fin_iso)
    except ValueError:
        return 0.0
    return max(0.0, (hasta - desde).total_seconds() / SEGUNDOS_POR_MINUTO)
