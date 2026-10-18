"""Muestras de la fila de espera para la métrica 6 (SPECS §16.1, A15 [DEC]).

Fuente (A15): el campo ``espera`` del latido ``EST`` del controlador
(``vehiculos_en_espera`` en el envoltorio, docs/protocolo_serial.md §2): es el
conteo físico de la zona de espera que ya muestra el sinóptico (§14.1). El
servidor no puede deducirlo por su cuenta: un vehículo en la fila todavía no
se identificó en garita.

Solo se guarda una muestra cuando el valor **cambia**: el latido llega cada
≤ 5 s y el máximo del periodo no necesita los repetidos. La consulta de la
métrica toma además la última muestra anterior al rango (el valor vigente al
empezar).
"""

import threading

from web.repositorios.repositorio_telemetria import RepositorioTelemetria


class MuestreoFilaEspera:
    """Convierte el latido en telemetría ``fila_espera`` sin duplicados consecutivos."""

    def __init__(self, telemetria: RepositorioTelemetria) -> None:
        self._telemetria = telemetria
        self._candado = threading.Lock()
        self._ultimo: int | None = None

    def registrar(self, valor: object, ts: str) -> bool:
        """Guarda la muestra si es un entero ≥ 0 distinto del anterior; True si la guardó."""
        if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
            return False
        with self._candado:
            if valor == self._ultimo:
                return False
            self._ultimo = valor
        self._telemetria.registrar_fila_espera(valor, ts)
        return True
