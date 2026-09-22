"""Enlace serie con pySerial: apertura, lectura no bloqueante y escritura (SPECS §4.2).

El protocolo define la interfaz ``PuertoSerie`` para poder inyectar un
duplicado de prueba en las pruebas unitarias (CODESTYLE T-5).
"""

import logging
from typing import Protocol

import serial

REGISTRO = logging.getLogger(__name__)

TIMEOUT_LECTURA_S = 0.05
TIMEOUT_ESCRITURA_S = 0.5


class PuertoSerie(Protocol):
    """Contrato mínimo del puerto serie usado por el núcleo del puente."""

    def abrir(self) -> None: ...

    def cerrar(self) -> None: ...

    @property
    def esta_abierto(self) -> bool: ...

    def leer_disponible(self) -> bytes: ...

    def escribir(self, datos: bytes) -> None: ...


class EnlaceSerie:
    """Implementación real del puerto serie con pySerial (velocidad sugerida 115200)."""

    def __init__(self, ruta_puerto: str, baudios: int) -> None:
        self._ruta_puerto = ruta_puerto
        self._baudios = baudios
        self._puerto: serial.Serial | None = None

    def abrir(self) -> None:
        self._puerto = serial.Serial(
            port=self._ruta_puerto,
            baudrate=self._baudios,
            timeout=TIMEOUT_LECTURA_S,
            write_timeout=TIMEOUT_ESCRITURA_S,
        )
        REGISTRO.info("Puerto serie abierto: %s a %d baudios", self._ruta_puerto, self._baudios)

    def cerrar(self) -> None:
        if self._puerto is not None:
            self._puerto.close()
            self._puerto = None
            REGISTRO.info("Puerto serie cerrado: %s", self._ruta_puerto)

    @property
    def esta_abierto(self) -> bool:
        return self._puerto is not None and self._puerto.is_open

    def leer_disponible(self) -> bytes:
        """Lee los bytes pendientes; sin datos devuelve b'' sin bloquear."""
        if self._puerto is None:
            return b""
        pendientes = self._puerto.in_waiting
        if pendientes == 0:
            return b""
        datos: bytes = self._puerto.read(pendientes)
        return datos

    def escribir(self, datos: bytes) -> None:
        if self._puerto is None:
            mensaje = "escritura sobre puerto serie cerrado"
            raise RuntimeError(mensaje)
        escritos = self._puerto.write(datos)
        if escritos is not None and escritos != len(datos):
            REGISTRO.warning("Escritura serial incompleta: %d de %d bytes", escritos, len(datos))
