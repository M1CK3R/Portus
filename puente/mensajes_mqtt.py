"""Envoltorio JSON, espacio de tópicos y reglas de publicación MQTT (SPECS §5).

El prefijo ``portus`` es obligatorio y exacto (SPECS §5.1); vive aquí como
``TOPIC_PREFIX`` y todos los tópicos se construyen con ``topico()``, nunca
concatenando texto a mano (CODESTYLE A-6).
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeAlias

from puente.protocolo import (
    TIPO_AGU,
    TIPO_ALM,
    TIPO_EST,
    TIPO_GAR,
    TIPO_GRU,
    TIPO_PAT,
    TIPO_PES,
    TIPO_RSP,
    TIPO_SAL,
    TIPO_TRF,
    Trama,
)

TOPIC_PREFIX = "portus"

TOPICO_EVT_GARITA = f"{TOPIC_PREFIX}/evt/garita"
TOPICO_EVT_PESAJE = f"{TOPIC_PREFIX}/evt/pesaje"
TOPICO_EVT_AGUJA = f"{TOPIC_PREFIX}/evt/aguja"
TOPICO_EVT_TRANSFERENCIA = f"{TOPIC_PREFIX}/evt/transferencia"
TOPICO_EVT_GRUA = f"{TOPIC_PREFIX}/evt/grua"
TOPICO_EVT_PATIO = f"{TOPIC_PREFIX}/evt/patio"
TOPICO_EVT_SALIDA = f"{TOPIC_PREFIX}/evt/salida"
TOPICO_EVT_ALARMA = f"{TOPIC_PREFIX}/evt/alarma"
TOPICO_EVT_ESTADO = f"{TOPIC_PREFIX}/evt/estado"
TOPICO_CMD_SOLICITUD = f"{TOPIC_PREFIX}/cmd/solicitud"
TOPICO_CMD_RESPUESTA = f"{TOPIC_PREFIX}/cmd/respuesta"
TOPICO_SRV_TURNO = f"{TOPIC_PREFIX}/srv/turno"
TOPICO_SRV_RETENCION = f"{TOPIC_PREFIX}/srv/retencion"
TOPICO_SRV_ALARMA = f"{TOPIC_PREFIX}/srv/alarma"
TOPICO_SRV_CITA = f"{TOPIC_PREFIX}/srv/cita"
TOPICO_SRV_ENLACE = f"{TOPIC_PREFIX}/srv/enlace"


def topico(*partes: str) -> str:
    """Construye un tópico con el prefijo obligatorio (SPECS §5.1)."""
    return "/".join((TOPIC_PREFIX, *partes))


TOPICO_COMODIN = topico("#")
"""Patrón de suscripción a todo el espacio de tópicos del proyecto.

Se construye con :func:`topico` en vez de escribir ``"portus/#"`` a mano en
cada lugar que se suscribe a todo (CODESTYLE A-6: una sola fuente de verdad
para el prefijo).
"""


TOPICO_POR_TIPO_TRAMA: dict[str, str] = {
    TIPO_GAR: TOPICO_EVT_GARITA,
    TIPO_PES: TOPICO_EVT_PESAJE,
    TIPO_AGU: TOPICO_EVT_AGUJA,
    TIPO_TRF: TOPICO_EVT_TRANSFERENCIA,
    TIPO_GRU: TOPICO_EVT_GRUA,
    TIPO_PAT: TOPICO_EVT_PATIO,
    TIPO_SAL: TOPICO_EVT_SALIDA,
    TIPO_ALM: TOPICO_EVT_ALARMA,
    TIPO_EST: TOPICO_EVT_ESTADO,
    TIPO_RSP: TOPICO_CMD_RESPUESTA,
}

QOS_EVENTOS = 1
QOS_LATIDO = 0
QOS_COMANDOS = 1

ORIGEN_CONTROLADOR = "controlador"
ORIGEN_PUENTE = "puente"
ORIGEN_SERVIDOR = "servidor"

TIPO_EVENTO_GARITA = "garita.identificacion"
TIPO_EVENTO_PESAJE = "pesaje.medicion"
TIPO_EVENTO_AGUJA = "aguja.estado"
TIPO_EVENTO_TRANSFERENCIA = "transferencia.evento"
TIPO_EVENTO_GRUA = "grua.paso"
TIPO_EVENTO_PATIO = "patio.cambio"
TIPO_EVENTO_SALIDA = "salida.verificacion"
TIPO_EVENTO_ALARMA_CONTROLADOR = "alarma.controlador"
TIPO_EVENTO_ESTADO = "estado.latido"
TIPO_EVENTO_COMANDO_RESPUESTA = "comando.respuesta"
TIPO_EVENTO_COMANDO_SOLICITUD = "comando.solicitud"
TIPO_EVENTO_ENLACE_ESTADO = "enlace.estado"
TIPO_EVENTO_ENLACE_SALTO = "enlace.salto_secuencia"
TIPO_EVENTO_ALARMA_SERVIDOR = "alarma.servidor"

TIPO_EVENTO_POR_TIPO_TRAMA: dict[str, str] = {
    TIPO_GAR: TIPO_EVENTO_GARITA,
    TIPO_PES: TIPO_EVENTO_PESAJE,
    TIPO_AGU: TIPO_EVENTO_AGUJA,
    TIPO_TRF: TIPO_EVENTO_TRANSFERENCIA,
    TIPO_GRU: TIPO_EVENTO_GRUA,
    TIPO_PAT: TIPO_EVENTO_PATIO,
    TIPO_SAL: TIPO_EVENTO_SALIDA,
    TIPO_ALM: TIPO_EVENTO_ALARMA_CONTROLADOR,
    TIPO_EST: TIPO_EVENTO_ESTADO,
    TIPO_RSP: TIPO_EVENTO_COMANDO_RESPUESTA,
}

TOPICO_POR_TIPO_EVENTO: dict[str, str] = {
    TIPO_EVENTO_GARITA: TOPICO_EVT_GARITA,
    TIPO_EVENTO_PESAJE: TOPICO_EVT_PESAJE,
    TIPO_EVENTO_AGUJA: TOPICO_EVT_AGUJA,
    TIPO_EVENTO_TRANSFERENCIA: TOPICO_EVT_TRANSFERENCIA,
    TIPO_EVENTO_GRUA: TOPICO_EVT_GRUA,
    TIPO_EVENTO_PATIO: TOPICO_EVT_PATIO,
    TIPO_EVENTO_SALIDA: TOPICO_EVT_SALIDA,
    TIPO_EVENTO_ALARMA_CONTROLADOR: TOPICO_EVT_ALARMA,
    TIPO_EVENTO_ESTADO: TOPICO_EVT_ESTADO,
    TIPO_EVENTO_COMANDO_RESPUESTA: TOPICO_CMD_RESPUESTA,
    TIPO_EVENTO_ENLACE_ESTADO: TOPICO_SRV_ENLACE,
    TIPO_EVENTO_ENLACE_SALTO: TOPICO_SRV_ENLACE,
    TIPO_EVENTO_ALARMA_SERVIDOR: TOPICO_SRV_ALARMA,
}

# Namespace fijo del proyecto: los identificadores deterministas derivan de aquí.
NAMESPACE_PORTUS = uuid.UUID("5e0f2c58-6f9b-4d1e-9a77-2b1c8d3a9f01")


def identificador_evento_controlador(seq: int, tipo_trama: str) -> str:
    """UUID determinista por (seq, tipo): la retransmisión tras SYN conserva el id.

    Así la deduplicación por ``id`` de los consumidores (SPECS §5.5) cubre
    también los eventos reenviados durante la reconciliación.
    """
    return str(uuid.uuid5(NAMESPACE_PORTUS, f"controlador:{seq}:{tipo_trama}"))


def identificador_respuesta_comando(cmd_id: str, estado: str, causa: str | None) -> str:
    """UUID determinista por (cmd_id, estado, causa): el reintento idempotente no duplica."""
    return str(uuid.uuid5(NAMESPACE_PORTUS, f"rsp:{cmd_id}:{estado}:{causa or ''}"))


def identificador_nuevo() -> str:
    """UUID aleatorio para mensajes propios del puente no derivados de tramas."""
    return str(uuid.uuid4())


def marca_tiempo_utc(ahora: datetime | None = None) -> str:
    """Marca de tiempo ISO 8601 UTC con milisegundos y sufijo Z (CODESTYLE I-8)."""
    instante = ahora if ahora is not None else datetime.now(UTC)
    return instante.strftime("%Y-%m-%dT%H:%M:%S.") + f"{instante.microsecond // 1000:03d}Z"


def _a_entero(texto: str) -> object:
    try:
        return int(texto)
    except ValueError:
        return texto


def _a_booleano(texto: str) -> object:
    if texto == "1":
        return True
    if texto == "0":
        return False
    return texto


def _texto(texto: str) -> object:
    return texto


ConversorCampo: TypeAlias = Callable[[str], object]

# Conversión de los campos de la trama serial a las claves JSON del envoltorio
# (SPECS §5.2: g→peso_g, n→muestras, meseta=1→true). Las claves de trama no
# listadas pasan tal cual; la tabla se comparte con el firmware (P-2).
CAMPOS_JSON_POR_TIPO: dict[str, dict[str, tuple[str, ConversorCampo]]] = {
    TIPO_GAR: {
        "veh": ("veh", _texto),
        "res": ("resultado", _texto),
        "causa": ("causa", _texto),
    },
    TIPO_PES: {
        "veh": ("veh", _texto),
        "g": ("peso_g", _a_entero),
        "n": ("muestras", _a_entero),
        "meseta": ("meseta", _a_booleano),
    },
    TIPO_AGU: {"estado": ("estado", _texto)},
    TIPO_TRF: {"evento": ("evento", _texto), "veh": ("veh", _texto)},
    TIPO_GRU: {
        "paso": ("paso", _texto),
        "pos": ("posicion", _texto),
        "nivel": ("nivel", _a_entero),
        "cont": ("contenedor", _texto),
        "res": ("resultado", _texto),
    },
    TIPO_PAT: {
        "pos": ("posicion", _texto),
        "nivel": ("nivel", _a_entero),
        "cont": ("contenedor", _texto),
        "estado": ("estado", _texto),
    },
    TIPO_SAL: {
        "veh": ("veh", _texto),
        "res": ("resultado", _texto),
        "causa": ("causa", _texto),
    },
    TIPO_ALM: {"cod": ("codigo", _texto), "sev": ("severidad", _texto)},
    TIPO_EST: {
        "modo": ("modo", _texto),
        "grua": ("grua", _texto),
        "aguja": ("aguja", _texto),
        "cola": ("trabajos_en_cola", _a_entero),
        "espera": ("vehiculos_en_espera", _a_entero),
        "err": ("errores_trama", _a_entero),
        "dif": ("eventos_diferidos", _a_entero),
        "link": ("enlace", _a_booleano),
    },
    TIPO_RSP: {"estado": ("estado", _texto), "causa": ("causa", _texto)},
}


def convertir_campos(tipo_trama: str, campos: dict[str, str]) -> dict[str, object]:
    """Convierte los campos serial al formato JSON del envoltorio (CODESTYLE N-5)."""
    tabla = CAMPOS_JSON_POR_TIPO.get(tipo_trama, {})
    datos: dict[str, object] = {}
    for clave_serial, valor_serial in campos.items():
        entrada = tabla.get(clave_serial)
        if entrada is None:
            datos[clave_serial] = valor_serial
        else:
            clave_json, conversor = entrada
            datos[clave_json] = conversor(valor_serial)
    return datos


@dataclass(frozen=True)
class MensajeMqtt:
    """Envoltorio tipado del mensaje publicado (SPECS §5.2)."""

    id: str
    ts: str
    origen: str
    tipo: str
    seq: int | None
    datos: dict[str, object]


def armar_mensaje(
    id: str,
    ts: str,
    origen: str,
    tipo: str,
    seq: int | None,
    datos: dict[str, object],
) -> MensajeMqtt:
    """Valida y empaqueta el envoltorio obligatorio: id, ts, origen, tipo, seq, datos."""
    return MensajeMqtt(id=id, ts=ts, origen=origen, tipo=tipo, seq=seq, datos=datos)


def mensaje_de_trama(trama: Trama, ts: str) -> MensajeMqtt:
    """Construye el mensaje MQTT de un evento del controlador."""
    return armar_mensaje(
        id=identificador_evento_controlador(trama.seq, trama.tipo),
        ts=ts,
        origen=ORIGEN_CONTROLADOR,
        tipo=TIPO_EVENTO_POR_TIPO_TRAMA[trama.tipo],
        seq=trama.seq,
        datos=convertir_campos(trama.tipo, trama.campos),
    )


def serializar_mensaje(mensaje: MensajeMqtt) -> str:
    """Serializa el envoltorio en JSON compacto; el formato es único en todos los tópicos."""
    contenido = {
        "id": mensaje.id,
        "ts": mensaje.ts,
        "origen": mensaje.origen,
        "tipo": mensaje.tipo,
        "seq": mensaje.seq,
        "datos": mensaje.datos,
    }
    return json.dumps(contenido, ensure_ascii=False, separators=(",", ":"))
