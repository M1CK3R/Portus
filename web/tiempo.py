"""Marcas de tiempo UTC de la web (CODESTYLE PY-5, BD-5).

Formato idéntico al del puente (``mensajes_mqtt.marca_tiempo_utc``): ISO 8601
con milisegundos y sufijo ``Z``, para que las filas de ``auditoria_rechazo`` y
``codigo_vinculacion`` comparen y se lean igual que las del puente.
"""

from datetime import UTC, datetime

FORMATO_MARCA = "%Y-%m-%dT%H:%M:%S."


def marca_utc(ahora: datetime | None = None) -> str:
    """Marca de tiempo ISO 8601 UTC con milisegundos y sufijo Z (CODESTYLE I-8)."""
    instante = ahora if ahora is not None else datetime.now(UTC)
    return instante.strftime(FORMATO_MARCA) + f"{instante.microsecond // 1000:03d}Z"


def instante_de_marca(marca: str) -> datetime:
    """Convierte una marca del proyecto en un datetime con zona horaria UTC."""
    instante = datetime.fromisoformat(marca)
    if instante.tzinfo is None:
        mensaje = f"la marca de tiempo '{marca}' no declara zona horaria (PY-5)"
        raise ValueError(mensaje)
    return instante
