"""Tareas periódicas del proceso portus-web (SPECS §13.1: AL12 «tarea periódica»).

Cada tarea corre en su propio hilo con ``Event.wait`` como temporizador, sin
bloquear a waitress ni al cliente MQTT (PY-4); la espera usa el reloj
monotónico del ``Event`` (D-9). Un fallo de una pasada se registra y la tarea
sigue en la siguiente (D-6): una alarma tardía es preferible a ninguna.
"""

import logging
import threading
from collections.abc import Callable

REGISTRO = logging.getLogger(__name__)


class TareaPeriodica:
    """Ejecuta ``accion`` cada ``periodo_s`` segundos hasta :meth:`detener`."""

    def __init__(self, nombre: str, periodo_s: float, accion: Callable[[], object]) -> None:
        if periodo_s <= 0:
            mensaje = f"periodo_s debe ser mayor que 0 (recibido: {periodo_s})"
            raise ValueError(mensaje)
        self._nombre = nombre
        self._periodo_s = periodo_s
        self._accion = accion
        self._detenida = threading.Event()
        self._hilo: threading.Thread | None = None

    def iniciar(self) -> None:
        """Lanza el hilo demonio; la primera pasada ocurre de inmediato."""
        self._hilo = threading.Thread(target=self._bucle, name=self._nombre, daemon=True)
        self._hilo.start()
        REGISTRO.info("Tarea periódica %s iniciada (cada %.0f s)", self._nombre, self._periodo_s)

    def detener(self) -> None:
        """Pide el fin y espera a que la pasada en curso termine (PY-6)."""
        self._detenida.set()
        if self._hilo is not None:
            self._hilo.join(timeout=self._periodo_s)
            self._hilo = None

    def ejecutar_una_vez(self) -> None:
        """Una pasada con el manejo de errores del bucle (la usan las pruebas)."""
        try:
            self._accion()
        except Exception:
            # D-6: se registra con traza y la tarea sigue viva para la próxima pasada.
            REGISTRO.exception("Tarea periódica %s falló en esta pasada", self._nombre)

    def _bucle(self) -> None:
        while not self._detenida.is_set():
            self.ejecutar_una_vez()
            self._detenida.wait(self._periodo_s)
