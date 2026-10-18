"""Control de secuencia del enlace y emisor de tramas del servidor (SPECS §4.2, §4.3).

Dos responsabilidades complementarias:

* ``RastreadorSecuencia`` vigila la secuencia creciente de los mensajes del
  controlador y detecta saltos, duplicados y retrasos.
* ``EmisorTramasServidor`` asigna la secuencia creciente a los mensajes del
  servidor (CMD, PING, SYN y los mensajes de servicio AUT/JOB de la Etapa 5).
"""

from dataclasses import dataclass
from enum import Enum

from puente.protocolo import (
    MODULO_SEQ,
    TIPO_CMD,
    TIPO_PING,
    TIPO_SYN,
    ContadorSecuenciaServidor,
    Trama,
)


class ClaseSecuencia(Enum):
    """Clasificación de un seq recibido respecto de la secuencia esperada."""

    NUEVO = "nuevo"
    SALTO = "salto"
    DUPLICADO = "duplicado"
    ATRASADO = "atrasado"


@dataclass(frozen=True)
class EventoSecuencia:
    """Resultado de registrar una seq en el rastreador."""

    clase: ClaseSecuencia
    seq: int
    seq_previa: int | None
    faltantes: int = 0


class RastreadorSecuencia:
    """Compara cada seq recibida con la anterior para detectar pérdidas (SPECS §4.2).

    La aritmética es módulo 2^32 porque SEQ es un entero sin signo de 32 bits.
    """

    def __init__(self) -> None:
        self._seq_previa: int | None = None

    @property
    def seq_previa(self) -> int | None:
        return self._seq_previa

    def registrar(self, seq: int) -> EventoSecuencia:
        previa = self._seq_previa
        self._seq_previa = seq
        if previa is None:
            return EventoSecuencia(clase=ClaseSecuencia.NUEVO, seq=seq, seq_previa=None)
        esperada = (previa + 1) % MODULO_SEQ
        if seq == esperada:
            return EventoSecuencia(clase=ClaseSecuencia.NUEVO, seq=seq, seq_previa=previa)
        if seq == previa:
            return EventoSecuencia(clase=ClaseSecuencia.DUPLICADO, seq=seq, seq_previa=previa)
        avance = (seq - esperada) % MODULO_SEQ
        if avance < MODULO_SEQ // 2:
            return EventoSecuencia(
                clase=ClaseSecuencia.SALTO, seq=seq, seq_previa=previa, faltantes=avance
            )
        return EventoSecuencia(clase=ClaseSecuencia.ATRASADO, seq=seq, seq_previa=previa)


class EmisorTramasServidor:
    """Serializa los mensajes S→C asignando la siguiente secuencia disponible."""

    def __init__(self, contador: ContadorSecuenciaServidor | None = None) -> None:
        self._contador = contador if contador is not None else ContadorSecuenciaServidor()

    @property
    def contador(self) -> ContadorSecuenciaServidor:
        return self._contador

    def armar_mensaje(self, tipo: str, campos: dict[str, str]) -> Trama:
        return Trama(seq=self._contador.siguiente(), tipo=tipo, campos=dict(campos))

    def armar_cmd(self, nombre: str, parametros: dict[str, str]) -> Trama:
        campos = {"nombre": nombre, **parametros}
        return self.armar_mensaje(TIPO_CMD, campos)

    def armar_ping(self) -> Trama:
        return self.armar_mensaje(TIPO_PING, {})

    def armar_syn(self, desde: int | None = None, volcar_estado: bool = False) -> Trama:
        if desde is None and not volcar_estado:
            mensaje = "SYN requiere al menos uno de: desde, volcar_estado"
            raise ValueError(mensaje)
        campos: dict[str, str] = {}
        if desde is not None:
            campos["desde"] = str(desde)
        if volcar_estado:
            campos["estado"] = "1"
        return self.armar_mensaje(TIPO_SYN, campos)
