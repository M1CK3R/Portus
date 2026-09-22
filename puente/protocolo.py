"""Constantes y utilidades del protocolo serial PORTUS (SPECS §4).

Trama ASCII delimitada: ``^SEQ|TIPO|CAMPOS#CRC\\n`` con CRC-16/CCITT-FALSE
calculado sobre los bytes entre ``^`` y ``#`` exclusivos. Los caracteres
reservados ``^ | # , \\n \\r %`` se escapan como ``%HH``.
"""

import threading
import time
from dataclasses import dataclass
from typing import TypeAlias

DELIMITADOR_INICIO = "^"
DELIMITADOR_FIN = "\n"
SEPARADOR_CAMPOS = ","
SEPARADOR_CRC = "#"
SEPARADOR_CLAVE_VALOR = "="
CARACTER_ESCAPE = "%"

CARACTERES_RESERVADOS = frozenset("^|#,\n\r%")
CARACTERES_VALIDOS_TRAMA = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789=.,|:#^-\r\n "
)

MAX_LONGITUD_SEQ_DIGITOS = 10
VALOR_MAXIMO_SEQ = 0xFFFFFFFF
MODULO_SEQ = 0x100000000

# El SPECS §4.2 dice "código de 3 letras" pero define PING con 4 (§4.3): se
# aceptan 3 a 4 letras y la decisión queda documentada en docs/protocolo_serial.md.
LONGITUD_TIPO_MIN_LETRAS = 3
LONGITUD_TIPO_MAX_LETRAS = 4

MIN_LONGITUD_TRAMA_BYTES = 13
MAX_LONGITUD_TRAMA_BYTES = 256

LONGITUD_CRC_DIGITOS = 4

CRC_POLINOMIO = 0x1021
CRC_VALOR_INICIAL = 0xFFFF


class ErrorProtocolo(Exception):
    """Violación del formato de trama o de una regla del protocolo (SPECS §4)."""


def calcular_crc16(datos: bytes) -> int:
    """CRC-16/CCITT-FALSE: polinomio 0x1021, valor inicial 0xFFFF, sin reflexión."""
    crc = CRC_VALOR_INICIAL
    for byte in datos:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ CRC_POLINOMIO) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def escapar(texto: str) -> str:
    """Sustituye los caracteres reservados del protocolo por su forma %HH."""
    fragmentos: list[str] = []
    for caracter in texto:
        if caracter in CARACTERES_RESERVADOS:
            fragmentos.append(f"%{ord(caracter):02X}")
        else:
            fragmentos.append(caracter)
    return "".join(fragmentos)


def desescapar(texto: str) -> str:
    """Recupera un texto escapado con %HH; lanza ErrorProtocolo si el escape es inválido."""
    fragmentos: list[str] = []
    indice = 0
    while indice < len(texto):
        caracter = texto[indice]
        if caracter != CARACTER_ESCAPE:
            fragmentos.append(caracter)
            indice += 1
            continue
        par_hex = texto[indice + 1 : indice + 3]
        if len(par_hex) != 2 or any(c not in "0123456789ABCDEF" for c in par_hex):
            raise ErrorProtocolo(f"escape %HH inválido en '{texto}' (posición {indice})")
        fragmentos.append(chr(int(par_hex, 16)))
        indice += 3
    return "".join(fragmentos)


@dataclass(frozen=True)
class Trama:
    """Trama validada del protocolo serial (SPECS §4.2)."""

    seq: int
    tipo: str
    campos: dict[str, str]

    def serializar_campos(self) -> str:
        pares: list[str] = []
        for clave, valor in self.campos.items():
            pares.append(f"{escapar(clave)}{SEPARADOR_CLAVE_VALOR}{escapar(valor)}")
        return SEPARADOR_CAMPOS.join(pares)

    def cuerpo_sin_crc(self) -> str:
        return f"{self.seq}|{self.tipo}|{self.serializar_campos()}"

    def armar_linea(self) -> str:
        crc = calcular_crc16(self.cuerpo_sin_crc().encode("ascii"))
        return (
            f"{DELIMITADOR_INICIO}{self.cuerpo_sin_crc()}"
            f"{SEPARADOR_CRC}{crc:0{LONGITUD_CRC_DIGITOS}X}{DELIMITADOR_FIN}"
        )


def _validar_seq(seq_texto: str) -> int:
    if not 1 <= len(seq_texto) <= MAX_LONGITUD_SEQ_DIGITOS or not seq_texto.isdigit():
        raise ErrorProtocolo(f"SEQ inválida: '{seq_texto}'")
    seq = int(seq_texto)
    if seq > VALOR_MAXIMO_SEQ:
        raise ErrorProtocolo(f"SEQ fuera de rango de 32 bits: {seq}")
    return seq


def _validar_tipo(tipo_texto: str) -> str:
    if (
        not LONGITUD_TIPO_MIN_LETRAS <= len(tipo_texto) <= LONGITUD_TIPO_MAX_LETRAS
        or not tipo_texto.isascii()
        or not tipo_texto.isupper()
        or not tipo_texto.isalpha()
    ):
        raise ErrorProtocolo(f"TIPO inválido: '{tipo_texto}'")
    if tipo_texto not in TIPOS_CONOCIDOS:
        raise ErrorProtocolo(f"TIPO desconocido: '{tipo_texto}'")
    return tipo_texto


def _parsear_campos(campos_texto: str) -> dict[str, str]:
    campos: dict[str, str] = {}
    if campos_texto == "":
        return campos
    for par in campos_texto.split(SEPARADOR_CAMPOS):
        if SEPARADOR_CLAVE_VALOR not in par:
            raise ErrorProtocolo(f"campo sin clave=valor: '{par}'")
        clave, _, valor = par.partition(SEPARADOR_CLAVE_VALOR)
        if clave == "":
            raise ErrorProtocolo(f"clave vacía en campo: '{par}'")
        campos[desescapar(clave)] = desescapar(valor)
    return campos


def parsear_linea(linea: str) -> Trama:
    """Valida y convierte una línea completa ``^...#CRC\\n`` en una Trama."""
    if not linea.startswith(DELIMITADOR_INICIO):
        raise ErrorProtocolo("la trama no inicia con '^'")
    if not linea.endswith(DELIMITADOR_FIN):
        raise ErrorProtocolo("la trama no termina con salto de línea")
    longitud = len(linea.encode("utf-8"))
    if longitud < MIN_LONGITUD_TRAMA_BYTES or longitud > MAX_LONGITUD_TRAMA_BYTES:
        raise ErrorProtocolo(f"longitud fuera de rango: {longitud} bytes")
    cuerpo = linea[1:]
    posicion_crc = cuerpo.find(SEPARADOR_CRC)
    if posicion_crc < 0:
        raise ErrorProtocolo("falta el separador '#'")
    contenido = cuerpo[:posicion_crc]
    crc_texto = cuerpo[posicion_crc + 1 : -1]
    if len(crc_texto) != LONGITUD_CRC_DIGITOS or any(
        c not in "0123456789ABCDEF" for c in crc_texto
    ):
        raise ErrorProtocolo(f"CRC mal formado: '{crc_texto}'")
    crc_calculado = calcular_crc16(contenido.encode("ascii"))
    if f"{crc_calculado:04X}" != crc_texto:
        raise ErrorProtocolo(f"CRC inválido: esperado {crc_texto}, calculado {crc_calculado:04X}")
    partes = contenido.split("|", maxsplit=2)
    if len(partes) != 3:
        raise ErrorProtocolo(f"estructura SEQ|TIPO|CAMPOS incompleta: '{contenido}'")
    seq = _validar_seq(partes[0])
    tipo = _validar_tipo(partes[1])
    campos = _parsear_campos(partes[2])
    return Trama(seq=seq, tipo=tipo, campos=campos)


@dataclass(frozen=True)
class TramaDescartada:
    """Resultado de descartar bytes o una trama inválida (SPECS §4.2)."""

    motivo: str
    detalle: str


ResultadoAnalisis: TypeAlias = Trama | TramaDescartada


class AnalizadorTramas:
    """Analizador incremental no bloqueante: alimenta bytes y devuelve tramas completas.

    Resincroniza en cada ``^`` y descarta el búfer si se desborda sin recibir ``\\n``.
    Toda resincronización que pierde bytes se reporta como ``TramaDescartada``
    (SPECS §4.2 regla 3: toda trama o secuencia de bytes descartada se cuenta).
    """

    def __init__(self, max_longitud_bytes: int = MAX_LONGITUD_TRAMA_BYTES) -> None:
        self._max_longitud_bytes = max_longitud_bytes
        self._bufer = bytearray()
        self._bytes_sin_inicio = 0

    def alimentar(self, datos: bytes) -> list[ResultadoAnalisis]:
        resultados: list[ResultadoAnalisis] = []
        for byte in datos:
            resultado = self._consumir_byte(byte)
            if resultado is not None:
                resultados.append(resultado)
        return resultados

    def _consumir_byte(self, byte: int) -> ResultadoAnalisis | None:
        if byte == ord(DELIMITADOR_INICIO):
            resultado = self._descarte_al_resincronizar()
            self._bufer = bytearray(DELIMITADOR_INICIO.encode("ascii"))
            return resultado
        if not self._bufer:
            self._bytes_sin_inicio += 1
            return None
        if byte == ord(DELIMITADOR_FIN):
            linea = self._bufer.decode("ascii", errors="replace") + DELIMITADOR_FIN
            self._bufer.clear()
            try:
                return parsear_linea(linea)
            except ErrorProtocolo as error:
                return TramaDescartada(motivo="trama_invalida", detalle=str(error))
        self._bufer.append(byte)
        if len(self._bufer) > self._max_longitud_bytes:
            longitud = len(self._bufer)
            self._bufer.clear()
            return TramaDescartada(
                motivo="trama_excede_longitud",
                detalle=f"{longitud} bytes sin delimitador de fin",
            )
        return None

    def _descarte_al_resincronizar(self) -> ResultadoAnalisis | None:
        """Reporta lo que se pierde justo antes de reiniciar el búfer en un ``^`` nuevo.

        Hay dos formas de perder bytes al resincronizar. La primera ya se
        contaba: ruido que llega sin ningún ``^`` por delante
        (``bytes_sin_inicio``). La segunda no se contaba y es la que corrige
        esta función: una trama que ya había empezado con ``^`` pero nunca
        llegó a su delimitador de fin antes de la siguiente ``^``
        (``trama_incompleta``); antes esos bytes desaparecían sin incrementar
        ningún contador, lo que podía subreportar ruido real de línea durante
        una operación prolongada (P01, SPECS §21.1).

        Ambos casos son mutuamente excluyentes: ``_bytes_sin_inicio`` solo
        crece mientras el búfer está vacío, así que a lo sumo uno de los dos
        ``if`` produce un resultado.
        """
        if self._bytes_sin_inicio > 0:
            detalle = f"{self._bytes_sin_inicio} bytes antes del delimitador de inicio"
            self._bytes_sin_inicio = 0
            return TramaDescartada(motivo="bytes_sin_inicio", detalle=detalle)
        if self._bufer:
            detalle = f"{len(self._bufer)} bytes sin delimitador de fin antes de un nuevo '^'"
            return TramaDescartada(motivo="trama_incompleta", detalle=detalle)
        return None


TIPO_GAR = "GAR"
TIPO_PES = "PES"
TIPO_AGU = "AGU"
TIPO_TRF = "TRF"
TIPO_GRU = "GRU"
TIPO_PAT = "PAT"
TIPO_SAL = "SAL"
TIPO_ALM = "ALM"
TIPO_EST = "EST"
TIPO_CMD = "CMD"
TIPO_RSP = "RSP"
TIPO_AUT = "AUT"
TIPO_JOB = "JOB"
TIPO_PING = "PING"
TIPO_SYN = "SYN"

TIPOS_EVENTO_CONTROLADOR = frozenset(
    {TIPO_GAR, TIPO_PES, TIPO_AGU, TIPO_TRF, TIPO_GRU, TIPO_PAT, TIPO_SAL, TIPO_ALM, TIPO_EST}
)
TIPOS_CONTROLADOR = TIPOS_EVENTO_CONTROLADOR | {TIPO_RSP}
TIPOS_SERVIDOR = frozenset({TIPO_CMD, TIPO_AUT, TIPO_JOB, TIPO_PING, TIPO_SYN})
TIPOS_CONOCIDOS = TIPOS_CONTROLADOR | TIPOS_SERVIDOR

CMD_ABRIR_TALANQUERA = "AbrirTalanquera"
CMD_CERRAR_TALANQUERA = "CerrarTalanquera"
CMD_ABRIR_PUERTA_SALIDA = "AbrirPuertaSalida"
CMD_AGUJA_RECTA = "AgujaRecta"
CMD_AGUJA_PARQUEO = "AgujaParqueo"
CMD_AGUJA_LIBERAR = "AgujaLiberar"
CMD_GRUA_REFERENCIAR = "GruaReferenciar"
CMD_GRUA_SUSPENDER = "GruaSuspender"
CMD_GRUA_REANUDAR = "GruaReanudar"
CMD_POSICION_BLOQUEAR = "PosicionBloquear"
CMD_POSICION_LIBERAR = "PosicionLiberar"
CMD_MODO_MANTENIMIENTO = "ModoMantenimiento"
CMD_ALARMA_SILENCIAR = "AlarmaSilenciar"

NOMBRES_COMANDOS = frozenset(
    {
        CMD_ABRIR_TALANQUERA,
        CMD_CERRAR_TALANQUERA,
        CMD_ABRIR_PUERTA_SALIDA,
        CMD_AGUJA_RECTA,
        CMD_AGUJA_PARQUEO,
        CMD_AGUJA_LIBERAR,
        CMD_GRUA_REFERENCIAR,
        CMD_GRUA_SUSPENDER,
        CMD_GRUA_REANUDAR,
        CMD_POSICION_BLOQUEAR,
        CMD_POSICION_LIBERAR,
        CMD_MODO_MANTENIMIENTO,
        CMD_ALARMA_SILENCIAR,
    }
)

CAUSA_SIN_RESPUESTA = "SIN_RESPUESTA"
CAUSA_COMANDO_DESCONOCIDO = "COMANDO_DESCONOCIDO"

CAUSAS_RECHAZO_COMANDO = frozenset(
    {
        "VEH_BAJO_TALANQUERA",
        "VEH_BAJO_PUERTA",
        "VEH_SOBRE_AGUJA",
        "PARQUEO_VACIO",
        "GRUA_CON_CARGA",
        "GRUA_EN_TRABAJO",
        "GRUA_EN_FALLA",
        "POS_EN_TRABAJO",
        "INCONSISTENCIA_PERSISTE",
        "VEH_EN_TRANSFERENCIA",
        CAUSA_SIN_RESPUESTA,
    }
)

ESTADO_ACK = "ACK"
ESTADO_NAK = "NAK"

CODIGO_ALARMA_ENLACE = "AL01"
SEVERIDAD_CRITICA = "CRITICA"
SEVERIDAD_ALTA = "ALTA"
SEVERIDAD_MEDIA = "MEDIA"
SEVERIDAD_BAJA = "BAJA"

CONTADOR_SECUENCIA_BASE_MAXIMA = 2**31


class ContadorSecuenciaServidor:
    """Secuencia creciente de mensajes servidor → controlador (SPECS §4.2).

    El valor inicial deriva del reloj de pared para no repetir secuencias ya
    atendidas por el controlador tras un reinicio del puente (idempotencia §4.5).
    """

    def __init__(self, seq_inicial: int | None = None) -> None:
        if seq_inicial is None:
            seq_inicial = int(time.time()) % CONTADOR_SECUENCIA_BASE_MAXIMA
        self._seq = seq_inicial % MODULO_SEQ
        self._candado = threading.Lock()

    def siguiente(self) -> int:
        with self._candado:
            self._seq = (self._seq + 1) % MODULO_SEQ
            return self._seq

    @property
    def valor_actual(self) -> int:
        with self._candado:
            return self._seq


def armar_trama_servidor(
    contador: ContadorSecuenciaServidor, tipo: str, campos: dict[str, str]
) -> Trama:
    """Construye una trama S→C con la siguiente secuencia disponible."""
    return Trama(seq=contador.siguiente(), tipo=tipo, campos=campos)
