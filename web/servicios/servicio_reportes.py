"""Reportes de corrida (SPECS §16.1, §16.3, Etapa 6): las 8 métricas y el CSV.

El cálculo sigue la serie conocida de §16.2 para poder validarlo. El CSV de
exportación lleva el detalle de cada turno del periodo y la política de
asignación activa (§12.4, §16.3).
"""

import csv
import io
from collections.abc import Callable
from datetime import datetime

from web.modelos.reporte import METRICAS, Reporte
from web.repositorios.repositorio_citas import RepositorioCitas
from web.repositorios.repositorio_reportes import RepositorioReportes
from web.repositorios.repositorio_retenciones import RepositorioRetenciones
from web.repositorios.repositorio_telemetria import RepositorioTelemetria
from web.repositorios.repositorio_trabajos import RepositorioTrabajos
from web.repositorios.repositorio_turnos import RepositorioTurnos
from web.tiempo import marca_utc


class ServicioReportes:
    """Genera y persiste los reportes de corrida con las 8 métricas (§16)."""

    def __init__(
        self,
        turnos: RepositorioTurnos,
        retenciones: RepositorioRetenciones,
        trabajos: RepositorioTrabajos,
        citas: RepositorioCitas,
        telemetria: RepositorioTelemetria,
        reportes: RepositorioReportes,
        politica: str,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._turnos = turnos
        self._retenciones = retenciones
        self._trabajos = trabajos
        self._citas = citas
        self._telemetria = telemetria
        self._reportes = reportes
        self._politica = politica
        self._fabrica_instante = fabrica_instante

    def generar(self, etiqueta: str, inicio: str, fin: str, generado_por: int | None) -> Reporte:
        """Calcula las 8 métricas del rango y persiste el reporte (§16.1, §16.3)."""
        resultado = self._calcular_metricas(inicio, fin)
        reporte_id = self._reportes.registrar(
            etiqueta=etiqueta,
            inicio=inicio,
            fin=fin,
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

    def exportar_csv(self, inicio: str, fin: str) -> str:
        """CSV con el detalle de cada turno del periodo y la política activa (§16.3)."""
        filas = self._turnos.detalle_csv_en_rango(inicio, fin)
        buf = io.StringIO()
        escritor = csv.writer(buf)
        escritor.writerow(
            [
                "# Política de asignación",
                self._politica,
            ]
        )
        escritor.writerow(
            [
                "turno",
                "vehiculo",
                "contenedor",
                "tipo_op",
                "estado",
                "peso_entrada_g",
                "peso_salida_g",
                "posicion_patio",
                "creado_en",
                "cerrado_en",
            ]
        )
        for f in filas:
            escritor.writerow([str(c) if c is not None else "" for c in f])
        return buf.getvalue()

    def _calcular_metricas(self, inicio: str, fin: str) -> dict[str, object]:
        """Las 8 métricas de §16.1 en el orden de la tabla [REQ]."""
        cerrados = self._turnos.cerrados_en_rango(inicio, fin)
        ciclos = self._trabajos.ciclos_en_rango(inicio, fin)
        retenciones = self._retenciones.resueltas_en_rango(inicio, fin)
        cumplidas, total_citas = self._citas.cumplimiento_en_rango(inicio, fin)
        fila_max = self._telemetria.max_fila_espera_en_rango(inicio, fin)

        # Métrica 1: remociones por contenedor retirado.
        remociones = sum(1 for c in ciclos if c.tipo.value == "REMOCION")
        retiros_cerrados = sum(1 for _, _, tipo in cerrados if tipo == "RETIRO")
        m1 = remociones / retiros_cerrados if retiros_cerrados else 0.0

        # Métrica 2: ciclos de grúa por operación completada.
        ciclos_completados = sum(1 for c in ciclos if c.resultado.value == "COMPLETADO")
        m2 = ciclos_completados / len(cerrados) if cerrados else 0.0

        # Métrica 3: distancia total recorrida por la grúa.
        m3 = sum(c.distancia_traslacion for c in ciclos)

        # Métrica 4: tiempo promedio de camión en la terminal (minutos).
        tiempos_camion = [_duracion_min(c[0], c[1]) for c in cerrados]
        m4 = sum(tiempos_camion) / len(tiempos_camion) if tiempos_camion else 0.0

        # Métrica 5: tiempo promedio de retención (minutos).
        tiempos_retencion = [_duracion_min(r[2], r[3]) for r in retenciones]
        m5 = sum(tiempos_retencion) / len(tiempos_retencion) if tiempos_retencion else 0.0

        # Métrica 6: longitud máxima de la fila de espera.
        m6 = fila_max

        # Métrica 7: % de citas cumplidas en ventana.
        m7 = (cumplidas / total_citas * 100) if total_citas else 0.0

        # Métrica 8: retenciones por causa y por resolución.
        por_causa_resolucion: dict[str, int] = {}
        for causa, resolucion, _, _ in retenciones:
            clave = f"{causa}/{resolucion}"
            por_causa_resolucion[clave] = por_causa_resolucion.get(clave, 0) + 1

        return {
            METRICAS[0]: round(m1, 4),
            METRICAS[1]: round(m2, 4),
            METRICAS[2]: m3,
            METRICAS[3]: round(m4, 2),
            METRICAS[4]: round(m5, 2),
            METRICAS[5]: m6,
            METRICAS[6]: round(m7, 2),
            METRICAS[7]: por_causa_resolucion,
        }


def _duracion_min(inicio_iso: str, fin_iso: str) -> float:
    """Minutos entre dos marcas ISO 8601 (UTC); 0 si alguna no parsea (D-5)."""
    try:
        desde = datetime.fromisoformat(inicio_iso.replace("Z", "+00:00"))
        hasta = datetime.fromisoformat(fin_iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (hasta - desde).total_seconds() / 60.0)
