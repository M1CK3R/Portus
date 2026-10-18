"""Parámetros de la lógica del turno (SPECS §12.4; CODESTYLE A-7).

``politica_asignacion`` selecciona el modo de asignación de posiciones del
patio: FASE1 por omisión (línea base obligatoria); la política optimizada de
la Fase 3 se agregará como nuevo modo. Se lee de ``config/portus.env``.
"""

from dataclasses import dataclass

from web.servicios.politica_asignacion import POLITICA_POR_OMISION, POLITICAS_DISPONIBLES


@dataclass(frozen=True)
class ConfiguracionLogica:
    """Parámetros propios del carril Aplicación; ninguno vive en el código (A-7)."""

    politica_asignacion: str = POLITICA_POR_OMISION

    @classmethod
    def desde_valores(cls, valores: dict[str, str]) -> "ConfiguracionLogica":
        """Extrae las claves propias de un portus.env ya parseado."""
        politica = valores.get("POLITICA_ASIGNACION", POLITICA_POR_OMISION)
        if politica not in POLITICAS_DISPONIBLES:
            mensaje = (
                f"POLITICA_ASIGNACION inválida: '{politica}' "
                f"(disponibles: {', '.join(POLITICAS_DISPONIBLES)})"
            )
            raise ValueError(mensaje)
        return cls(politica_asignacion=politica)
