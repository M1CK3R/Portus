"""Usuario y roles del sistema (SPECS §7.1, §7.2, §17.1).

Cinco roles y ningún otro. Cuatro operan en la web; TRANSPORTISTA solo por
el canal de mensajería (§7.1), así que su inicio de sesión web se rechaza.
"""

from dataclasses import dataclass
from enum import StrEnum


class Rol(StrEnum):
    """Identificadores exactos de los cinco roles (SPECS §7.1)."""

    TERMINAL = "TERMINAL"
    NAVIERA = "NAVIERA"
    AGENTE = "AGENTE"
    AUTORIDAD = "AUTORIDAD"
    TRANSPORTISTA = "TRANSPORTISTA"


ROLES_WEB: frozenset[Rol] = frozenset({Rol.TERMINAL, Rol.NAVIERA, Rol.AGENTE, Rol.AUTORIDAD})
"""Roles con acceso a la interfaz web; TRANSPORTISTA queda fuera (§7.1)."""


@dataclass(frozen=True)
class Usuario:
    """Usuario del sistema; ``id`` es la identidad de propiedad de NAVIERA.

    El filtro de propiedad de §7.5.2 usa este id: un manifiesto de la naviera
    X lleva ``naviera_id`` igual al ``id`` del usuario NAVIERA de la naviera X.
    El hash de la contraseña no viaja en el modelo: vive solo en el
    repositorio (S-3).
    """

    id: int
    username: str
    rol: Rol
    nombre_mostrado: str
    activo: bool = True


def rol_de_texto(texto: str) -> Rol:
    """Convierte el texto del rol guardado en la base de datos en un Rol."""
    try:
        return Rol(texto)
    except ValueError as error:
        mensaje = f"rol desconocido en la base de datos: '{texto}'"
        raise ValueError(mensaje) from error
