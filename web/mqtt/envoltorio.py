"""Envoltorio JSON y tópicos del lado web (SPECS §5.2, §5.3; CODESTYLE A-6).

Espejo deliberado de ``puente/mensajes_mqtt``: dos servicios independientes
en el SBC que comparten el contrato, no el proceso. El archivo
``docs/constantes_protocolo.json`` es la fuente de paridad y la prueba
``test_paridad_constantes.py`` verifica que ambos lados coinciden (P-2).
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

TOPIC_PREFIX = "portus"

TOPICO_CMD_SOLICITUD = f"{TOPIC_PREFIX}/cmd/solicitud"
TOPICO_SRV_TURNO = f"{TOPIC_PREFIX}/srv/turno"
TOPICO_SRV_RETENCION = f"{TOPIC_PREFIX}/srv/retencion"
TOPICO_SRV_ALARMA = f"{TOPIC_PREFIX}/srv/alarma"

ORIGEN_SERVIDOR = "servidor"

TIPO_TURNO_AUTORIZACION = "turno.autorizacion"
TIPO_TURNO_TRABAJO = "turno.trabajo"
TIPO_TURNO_CAMBIO = "turno.cambio"
TIPO_RETENCION_ABIERTA = "retencion.abierta"
TIPO_RETENCION_RESUELTA = "retencion.resuelta"
TIPO_ALARMA_SERVIDOR = "alarma.servidor"
TIPO_COMANDO_SOLICITUD = "comando.solicitud"


def topico(*partes: str) -> str:
    """Construye un tópico con el prefijo obligatorio (SPECS §5.1)."""
    return "/".join((TOPIC_PREFIX, *partes))


TOPICO_COMODIN = topico("#")


def marca_utc(ahora: datetime | None = None) -> str:
    """Marca ISO 8601 UTC con milisegundos y sufijo Z (CODESTYLE I-8)."""
    instante = ahora if ahora is not None else datetime.now(UTC)
    return instante.strftime("%Y-%m-%dT%H:%M:%S.") + f"{instante.microsecond // 1000:03d}Z"


def identificador_nuevo() -> str:
    """UUID aleatorio para mensajes propios del servidor (§5.2)."""
    return str(uuid.uuid4())


@dataclass(frozen=True)
class MensajeServidor:
    """Envoltorio tipado que la lógica publica (SPECS §5.2)."""

    id: str
    ts: str
    origen: str
    tipo: str
    seq: int | None
    datos: dict[str, object]


def serializar_mensaje(mensaje: MensajeServidor) -> str:
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
