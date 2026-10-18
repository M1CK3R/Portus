"""Código de vinculación de un transportista (SPECS §15.1, §17.1, A17)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CodigoVinculacion:
    """Código de un solo uso, vigente 60 minutos, asociado a un transportista.

    Se guarda en claro porque vive 60 minutos, es de un solo uso y se
    invalida al generar otro para el mismo transportista (§15.1 [PROP]); la
    comparación en tiempo constante ocurre al consumirlo (PY-8).
    """

    codigo: str
    transportista_id: int
    creado_en: str
    expira_en: str
    usado_en: str | None = None
