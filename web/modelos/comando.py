"""Comandos remotos (SPECS §6): textos de causa de rechazo y estado del controlador.

Los códigos viven una vez en ``puente.protocolo`` (P-2); aquí se les da el
texto legible que exige §6.2 regla 2 («causa exacta») y se modela lo que el
servidor sabe del controlador por el latido para aplicar la disponibilidad de
los controles de §6.3 también en el servidor.
"""

from dataclasses import dataclass

TEXTO_CAUSA_RECHAZO: dict[str, str] = {
    "VEH_BAJO_TALANQUERA": "Hay un vehículo detectado bajo la talanquera",
    "VEH_BAJO_PUERTA": "Hay un vehículo detectado bajo la puerta de salida",
    "VEH_SOBRE_AGUJA": "Hay un vehículo sobre la aguja",
    "PARQUEO_VACIO": "No hay vehículo en el parqueo",
    "GRUA_CON_CARGA": "La grúa tiene carga adherida",
    "GRUA_EN_TRABAJO": "Hay un trabajo de grúa en ejecución",
    "GRUA_EN_FALLA": "La grúa está en falla sin rearme",
    "POS_EN_TRABAJO": "La posición es origen o destino de un trabajo en ejecución",
    "INCONSISTENCIA_PERSISTE": "La inconsistencia física que originó el bloqueo persiste",
    "VEH_EN_TRANSFERENCIA": "Hay un vehículo en transferencia",
    "SIN_RESPUESTA": "El controlador no respondió (generado por el puente)",
}
"""Textos sugeridos de §6.5; la paridad con los códigos la verifica una prueba."""

GRUA_SUSPENDIDA = "SUSPENDIDA"
GRUA_REPOSO = "REPOSO"
ESTADOS_GRUA_REFERENCIABLE = frozenset({GRUA_REPOSO, GRUA_SUSPENDIDA})
"""§6.3: Referenciar solo con la grúa en reposo o suspendida."""


def texto_causa(codigo: str | None) -> str:
    """Texto para el usuario; un código desconocido se muestra tal cual (D-10)."""
    if not codigo:
        return "sin causa informada"
    return TEXTO_CAUSA_RECHAZO.get(codigo, codigo)


@dataclass(frozen=True)
class EstadoControlador:
    """Último latido ``EST`` visto por la web (§5.4): modo y estado de la grúa."""

    modo: str
    grua: str
    ts: str
