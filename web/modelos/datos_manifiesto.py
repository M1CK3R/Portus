"""Datos del manifiesto que el servidor usa para revalidar el pesaje (A5)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DatosManifiesto:
    """Peso declarado y tolerancia vigentes del manifiesto del turno (§9.3, A5)."""

    peso_declarado_g: int
    tolerancia_pct: float
