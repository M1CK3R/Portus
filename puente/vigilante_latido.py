"""Vigilancia del latido del controlador y generación de AL01 (SPECS §5.4, §3.4).

El latido viaja en ``portus/evt/estado`` con periodo ≤ 5 s. Si deja de llegar
durante tres periodos consecutivos, el servidor declara el enlace perdido y
genera AL01 (crítica). La alarma no se retira sola: permanece activa hasta
que un usuario la reconoce (SPECS §13.2); el vigilante solo reporta el
cambio de estado del enlace en ``portus/srv/enlace``.

La lógica es pura y con reloj inyectable (CODESTYLE T-3): el orquestador
llama a ``registrar_latido`` y ``comprobar`` desde sus hilos.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from puente.protocolo import CODIGO_ALARMA_ENLACE, SEVERIDAD_CRITICA

MS_POR_SEGUNDO = 1000
DESCRIPCION_AL01 = "Enlace con el controlador perdido"


class EstadoEnlace(Enum):
    ACTIVO = "activo"
    PERDIDO = "perdido"


@dataclass(frozen=True)
class TransicionEnlace:
    """Cambio de estado del enlace detectado por el vigilante."""

    estado_nuevo: EstadoEnlace
    estado_previo: EstadoEnlace
    ms_sin_latido: int
    ultimo_latido_ms: int


class VigilanteLatido:
    """Declara el enlace perdido tras el umbral de tres periodos (SPECS §5.4)."""

    def __init__(self, umbral_ms: int, arranque_ms: int) -> None:
        self._umbral_ms = umbral_ms
        self._ultimo_latido_ms = arranque_ms
        self._estado = EstadoEnlace.ACTIVO

    @property
    def umbral_ms(self) -> int:
        """Umbral de tres periodos sin latido en ms (SPECS §5.4)."""
        return self._umbral_ms

    @property
    def estado(self) -> EstadoEnlace:
        return self._estado

    @property
    def ultimo_latido_ms(self) -> int:
        return self._ultimo_latido_ms

    def registrar_latido(self, instante_ms: int) -> None:
        """Anota la llegada de un latido o de cualquier mensaje válido del controlador."""
        self._ultimo_latido_ms = instante_ms
        self._estado = EstadoEnlace.ACTIVO

    def comprobar(self, ahora_ms: int) -> TransicionEnlace | None:
        """Evalúa el umbral; devuelve la transición solo cuando el estado cambia."""
        ms_sin_latido = ahora_ms - self._ultimo_latido_ms
        if self._estado is EstadoEnlace.ACTIVO:
            if ms_sin_latido < self._umbral_ms:
                return None
            estado_previo = self._estado
            self._estado = EstadoEnlace.PERDIDO
            return TransicionEnlace(
                estado_nuevo=EstadoEnlace.PERDIDO,
                estado_previo=estado_previo,
                ms_sin_latido=ms_sin_latido,
                ultimo_latido_ms=self._ultimo_latido_ms,
            )
        return None


def datos_al01(ms_sin_latido_ms: int, retroactiva: bool = False) -> dict[str, object]:
    """Arma el bloque ``datos`` del mensaje de AL01 en portus/srv/alarma."""
    return {
        "codigo": CODIGO_ALARMA_ENLACE,
        "severidad": SEVERIDAD_CRITICA,
        "descripcion": DESCRIPCION_AL01,
        "ms_sin_latido": ms_sin_latido_ms,
        "retroactiva": retroactiva,
    }


def evaluar_al01_retroactiva(
    ultimo_latido_ts: str | None,
    ahora: datetime,
    umbral_ms: int,
) -> dict[str, object] | None:
    """Detecta al arrancar una caída previa del enlace y devuelve los datos de AL01 (A14).

    Compara la marca del último latido guardado por la persistencia con la hora
    de arranque; si el hueco supera el umbral de tres periodos, la alarma se
    registra retroactiva con el inicio y el fin de la pérdida (SPECS §25 A14).
    Devuelve None si no hay latido previo o si el enlace no estuvo perdido.
    """
    if ultimo_latido_ts is None:
        return None
    try:
        texto = ultimo_latido_ts.replace("Z", "+00:00")
        ultimo = datetime.fromisoformat(texto)
    except ValueError as error:
        raise ValueError(f"marca de latido inválida: '{ultimo_latido_ts}'") from error
    if ultimo.tzinfo is None:
        ultimo = ultimo.replace(tzinfo=UTC)
    ms_sin_latido = int((ahora - ultimo).total_seconds() * MS_POR_SEGUNDO)
    if ms_sin_latido <= umbral_ms:
        return None
    return {
        "codigo": CODIGO_ALARMA_ENLACE,
        "severidad": SEVERIDAD_CRITICA,
        "descripcion": DESCRIPCION_AL01,
        "ms_sin_latido": ms_sin_latido,
        "retroactiva": True,
        "desde": ultimo_latido_ts,
        "hasta": ahora.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ahora.microsecond // 1000:03d}Z",
    }
