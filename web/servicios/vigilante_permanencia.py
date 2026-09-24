"""AL13: contenedor con permanencia superior a dos horas (SPECS §12.2, §13.1).

La pestaña Patio resalta la fila en el navegador; esta tarea periódica genera
la alarma **una vez por estadía** del contenedor (clave «contenedor|ingreso»
en ``alerta_emitida``): si sale y vuelve a entrar, se vigila de nuevo. Reloj
inyectable (T-3) y sin hilos propios: la llama ``web.planificador``.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from web.modelos.alarma import CodigoAlarma
from web.modelos.patio import PERMANENCIA_EXCESIVA_HORAS
from web.repositorios.repositorio_alarmas import RepositorioAlarmas
from web.repositorios.repositorio_inventario import RepositorioInventario
from web.servicios.emisor_alarmas import EmisorAlarmas
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

SEGUNDOS_POR_HORA = 3600


class VigilantePermanencia:
    """Genera AL13 por cada contenedor del patio que supera el umbral de §12.2."""

    def __init__(
        self,
        inventario: RepositorioInventario,
        alarmas: RepositorioAlarmas,
        emisor: EmisorAlarmas,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._inventario = inventario
        self._alarmas = alarmas
        self._emisor = emisor
        self._fabrica_instante = fabrica_instante

    def revisar(self) -> list[str]:
        """Emite AL13 para las estadías excedidas aún sin alerta; devuelve los contenedores."""
        ahora = self._fabrica_instante()
        limite = ahora - timedelta(hours=PERMANENCIA_EXCESIVA_HORAS)
        ya_alertadas = self._alarmas.claves_alertadas(CodigoAlarma.AL13.value)
        alertados: list[str] = []
        for celda in self._inventario.celdas():
            if celda.contenedor_id is None or celda.ingreso_en is None:
                continue
            clave = f"{celda.contenedor_id}|{celda.ingreso_en}"
            if clave in ya_alertadas or _instante(celda.ingreso_en) > limite:
                continue
            horas = (ahora - _instante(celda.ingreso_en)).total_seconds() / SEGUNDOS_POR_HORA
            datos: dict[str, object] = {
                "contenedor": celda.contenedor_id,
                "posicion": celda.posicion,
                "nivel": celda.nivel,
                "ingreso_en": celda.ingreso_en,
                "permanencia_h": round(horas, 1),
            }
            ts = marca_utc(ahora)
            alarma_id = self._emisor.emitir(CodigoAlarma.AL13, datos, ts)
            self._alarmas.registrar_alerta(CodigoAlarma.AL13.value, clave, alarma_id, ts)
            alertados.append(celda.contenedor_id)
            REGISTRO.warning(
                "AL13: %s en %s/N%d lleva %.1f h en el patio",
                celda.contenedor_id,
                celda.posicion,
                celda.nivel,
                horas,
            )
        return alertados


def _instante(iso: str) -> datetime:
    """ISO 8601 del inventario → datetime UTC (acepta el sufijo ``Z``, PY-5)."""
    instante = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return instante if instante.tzinfo is not None else instante.replace(tzinfo=UTC)
