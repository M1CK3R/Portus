"""Pestaña Grúa (SPECS §12.6, Etapa 6): estado, ciclos, fallas y exportación.

La grúa es única: a lo sumo un trabajo ``EN_CURSO``. El historial de fallas
viene de las alarmas AL03/AL04/AL05/AL06 (§13.1); el de ciclos, de la tabla
``ciclo_grua`` (§12.6). La exportación CSV lleva el detalle de cada ciclo del
rango seleccionado.
"""

import csv
import io
from collections.abc import Callable
from datetime import datetime

from web.modelos.ciclo_grua import CicloGrua, FallaGrua
from web.modelos.trabajos import Trabajo
from web.repositorios.repositorio_alarmas import RepositorioAlarmas
from web.repositorios.repositorio_trabajos import RepositorioTrabajos
from web.servicios.puertos import PublicadorLogica
from web.tiempo import marca_utc


class ServicioGrua:
    """Estado de la grúa, gráfica de ciclos e historial de fallas (§12.6)."""

    def __init__(
        self,
        trabajos: RepositorioTrabajos,
        alarmas: RepositorioAlarmas,
        publicador: PublicadorLogica,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._trabajos = trabajos
        self._alarmas = alarmas
        self._publicador = publicador
        self._fabrica_instante = fabrica_instante

    def estado(self) -> dict[str, object]:
        """Posición/trabajo en curso, cola pendiente y resumen de ciclos (§12.6)."""
        en_curso = self._trabajos.en_curso_global()
        cola = self._trabajos.cola_pendiente()
        return {
            "en_curso": _trabajo_a_dict(en_curso) if en_curso is not None else None,
            "cola_pendiente": [_trabajo_a_dict(t) for t in cola],
            "cantidad_pendiente": len(cola),
        }

    def ciclos(self, limite: int) -> list[CicloGrua]:
        """Últimos ``limite`` ciclos para la gráfica (§12.6: selector 50/100/200)."""
        return self._trabajos.ciclos_ultimos(limite)

    def historial_fallas(self) -> list[FallaGrua]:
        """Historial de fallas de la grúa (§12.6: AL03, AL04, AL05, AL06)."""
        fallas: list[FallaGrua] = []
        for alarma in self._alarmas.fallas_de_grua():
            fallas.append(
                FallaGrua(
                    codigo=alarma.codigo,
                    descripcion=alarma.descripcion,
                    ts=alarma.ts,
                    datos=alarma.datos,
                )
            )
        return fallas

    def exportar_csv(self, inicio: str, fin: str) -> str:
        """CSV con el detalle de cada ciclo del rango (§12.6: exportar historial).

        Columnas: id, turno, trabajo, tipo, ts_inicio, ts_fin, distancia, resultado.
        """
        ciclos = self._trabajos.ciclos_en_rango(inicio, fin)
        buf = io.StringIO()
        escritor = csv.writer(buf)
        escritor.writerow(
            ["id", "turno", "trabajo", "tipo", "ts_inicio", "ts_fin", "distancia", "resultado"]
        )
        for c in ciclos:
            escritor.writerow(
                [
                    c.id,
                    c.turno_id,
                    c.trabajo_id if c.trabajo_id is not None else "",
                    c.tipo.value,
                    c.ts_inicio,
                    c.ts_fin,
                    c.distancia_traslacion,
                    c.resultado.value,
                ]
            )
        return buf.getvalue()


def _trabajo_a_dict(t: Trabajo) -> dict[str, object]:
    return {
        "id": t.id,
        "turno": t.turno_id,
        "tipo": t.tipo.value,
        "contenedor": t.contenedor_id,
        "origen": t.origen,
        "destino": t.destino,
        "nivel": t.nivel,
        "orden": t.orden,
    }


def ahora(fabrica_instante: Callable[[], datetime]) -> str:
    """Marca UTC actual; helper de la pestaña para los rangos por omisión."""
    return marca_utc(fabrica_instante())
