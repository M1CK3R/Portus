"""Utilidades compartidas de prueba: relojes falsos y duplicados de frontera (T-3)."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

INSTANTE_FIJO = datetime(2026, 9, 20, 14, 3, 22, 418000, tzinfo=UTC)
MARCA_TIEMPO_FIJA = "2026-09-20T14:03:22.418Z"


class RelojFalso:
    """Reloj monotónico inyectable para pruebas deterministas (CODESTYLE T-3)."""

    def __init__(self, inicial_ms: int = 0) -> None:
        self._ahora_ms = inicial_ms

    def __call__(self) -> int:
        return self._ahora_ms

    def avanzar(self, ms: int) -> None:
        self._ahora_ms += ms


class RelojUtcFalso:
    """Reloj de pared UTC inyectable que avanza sincronizado con el monotónico."""

    def __init__(self, instante_inicial: datetime = INSTANTE_FIJO) -> None:
        self._ahora = instante_inicial

    def __call__(self) -> datetime:
        return self._ahora

    def avanzar_ms(self, ms: int) -> None:
        self._ahora = self._ahora + timedelta(milliseconds=ms)


@dataclass(frozen=True)
class Publicacion:
    """Una publicación capturada hacia el broker."""

    topico: str
    datos: str
    qos: int
    retain: bool

    def json(self) -> dict[str, object]:
        return json.loads(self.datos)


@dataclass
class SalidaFalsa:
    """SalidaMqtt de prueba que captura todas las publicaciones."""

    publicaciones: list[Publicacion] = field(default_factory=list)

    def publicar(self, topico: str, datos: str, qos: int, retain: bool) -> None:
        self.publicaciones.append(Publicacion(topico=topico, datos=datos, qos=qos, retain=retain))

    def json(self, indice: int = -1) -> dict[str, object]:
        return self.publicaciones[indice].json()

    def topicos(self) -> list[str]:
        return [publicacion.topico for publicacion in self.publicaciones]


class PuertoSerieFalso:
    """PuertoSerie de prueba: recibe tramas inyectadas y captura las escritas."""

    def __init__(self) -> None:
        self.recibidos: list[bytes] = []
        self.pendientes = bytearray()
        self.abierto = False

    def abrir(self) -> None:
        self.abierto = True

    def cerrar(self) -> None:
        self.abierto = False

    @property
    def esta_abierto(self) -> bool:
        return self.abierto

    def leer_disponible(self) -> bytes:
        datos = bytes(self.pendientes)
        self.pendientes.clear()
        return datos

    def escribir(self, datos: bytes) -> None:
        self.recibidos.append(bytes(datos))

    def inyectar(self, datos: bytes) -> None:
        self.pendientes.extend(datos)

    def recibido(self) -> bytes:
        return b"".join(self.recibidos)


class FechaFabrica(Protocol):
    """Fábrica de instantes UTC determinista."""

    def __call__(self) -> datetime: ...
