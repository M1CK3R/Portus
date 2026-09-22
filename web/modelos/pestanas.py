"""Pestañas visibles por rol (SPECS §7.6).

Los nombres y la cantidad son obligatorios: se permite agregar pestañas,
nunca eliminar ni fusionar. La navegación se construye en el servidor a
partir de esta tabla, de modo que un rol jamás recibe el enlace de una
pestaña que no le corresponde.
"""

from dataclasses import dataclass

from web.modelos.usuario import Rol


@dataclass(frozen=True)
class Pestana:
    """Una pestaña de la interfaz: ``slug`` en la URL y título visible."""

    slug: str
    titulo: str


PESTANAS_POR_ROL: dict[Rol, tuple[Pestana, ...]] = {
    Rol.TERMINAL: (
        Pestana("operacion", "Operación"),
        Pestana("turnos", "Turnos"),
        Pestana("retenciones", "Retenciones"),
        Pestana("patio", "Patio"),
        Pestana("grua", "Grúa"),
        Pestana("alarmas", "Alarmas"),
        Pestana("citas", "Citas"),
        Pestana("reportes", "Reportes"),
    ),
    Rol.NAVIERA: (
        Pestana("manifiestos", "Manifiestos"),
        Pestana("mis_contenedores", "Mis contenedores"),
    ),
    Rol.AGENTE: (
        Pestana("declaraciones", "Declaraciones"),
        Pestana("seguimiento", "Seguimiento"),
    ),
    Rol.AUTORIDAD: (
        Pestana("solicitudes_levante", "Solicitudes de levante"),
        Pestana("retenciones_aduaneras", "Retenciones aduaneras"),
        Pestana("consulta_carga", "Consulta de carga"),
    ),
    # TRANSPORTISTA no tiene interfaz web (§7.6): opera por mensajería.
    Rol.TRANSPORTISTA: (),
}

ETIQUETA_ETAPA_POR_SLUG: dict[str, str] = {
    "operacion": "Etapa 5 (sinóptico por suscripción MQTT sobre WebSocket)",
    "turnos": "Etapa 5 (máquina de estados) y Etapa 6 (línea de tiempo)",
    "retenciones": "Etapa 5 (resoluciones) y Etapa 6 (bandeja)",
    "patio": "Etapa 5 (inventario) y Etapa 6 (consulta)",
    "grua": "Etapa 5 (trabajos) y Etapa 6 (ciclos)",
    "alarmas": "Etapa 5 (catálogo) y Etapa 6 (reconocimiento)",
    "citas": "Etapa 5 (agenda) y Etapa 6 (panel de vinculación, A17)",
    "reportes": "Etapa 11 (métricas y exportación)",
    "manifiestos": "Etapa 5 (creación y ciclo documental)",
    "mis_contenedores": "Etapa 7 (consulta de carga propia)",
    "declaraciones": "Etapa 7 (presentación de declaración)",
    "seguimiento": "Etapa 7 (seguimiento de manifiestos)",
    "solicitudes_levante": "Etapa 7 (otorgar o retener levante)",
    "retenciones_aduaneras": "Etapa 7 (bandeja aduanera)",
    "consulta_carga": "Etapa 7 (consulta de ubicación)",
}


def pestanas_de_rol(rol: Rol) -> tuple[Pestana, ...]:
    """Devuelve las pestañas exactas del rol (§7.6); vacío para TRANSPORTISTA."""
    return PESTANAS_POR_ROL[rol]


def pestana_por_slug(rol: Rol, slug: str) -> Pestana | None:
    """Busca el slug dentro de las pestañas del rol; None si no le pertenece."""
    for pestana in PESTANAS_POR_ROL[rol]:
        if pestana.slug == slug:
            return pestana
    return None
