"""Sesión del usuario sobre la cookie firmada de Flask (SPECS §7.3 [PROP]).

La cookie es ``HttpOnly`` y ``SameSite=Lax`` (se fija en ``aplicacion``), la
firma la aplica Flask con la clave secreta de ``portus.env`` (S-1) y la
expiración por inactividad la controla ``aplicacion`` con un reloj
inyectable (T-3). Las funciones de aquí solo tipan el acceso al diccionario
de sesión para que ningún módulo toque claves sueltas.
"""

from collections.abc import Mapping, MutableMapping

from web.modelos.usuario import Rol, Usuario

CLAVE_USUARIO_ID = "usuario_id"
CLAVE_USERNAME = "username"
CLAVE_ROL = "rol"
CLAVE_NOMBRE = "nombre_mostrado"
CLAVE_ULTIMO_ACCESO_S = "ultimo_acceso_s"


def iniciar_sesion(sesion: MutableMapping[str, object], usuario: Usuario, momento_s: float) -> None:
    """Deja al usuario en la sesión y anota el instante del acceso."""
    sesion[CLAVE_USUARIO_ID] = usuario.id
    sesion[CLAVE_USERNAME] = usuario.username
    sesion[CLAVE_ROL] = usuario.rol.value
    sesion[CLAVE_NOMBRE] = usuario.nombre_mostrado
    sesion[CLAVE_ULTIMO_ACCESO_S] = momento_s


def cerrar_sesion(sesion: MutableMapping[str, object]) -> None:
    """Cierra de forma explícita la sesión (§7.3: cierre de sesión explícito)."""
    sesion.clear()


def usuario_en_sesion(sesion: Mapping[str, object]) -> Usuario | None:
    """Reconstruye el usuario de la sesión; None si no hay sesión válida.

    La cookie está firmada, así que las claves no son manipulables desde el
    cliente; aun así se valida el tipo y el rol por si la clave de firma
    cambió entre despliegues (la sesión vieja simplemente no se restaura).
    """
    id_valor = sesion.get(CLAVE_USUARIO_ID)
    username_valor = sesion.get(CLAVE_USERNAME)
    rol_valor = sesion.get(CLAVE_ROL)
    nombre_valor = sesion.get(CLAVE_NOMBRE)
    if not isinstance(id_valor, int) or not isinstance(username_valor, str):
        return None
    if not isinstance(rol_valor, str) or not isinstance(nombre_valor, str):
        return None
    try:
        rol = Rol(rol_valor)
    except ValueError:
        return None
    return Usuario(id=id_valor, username=username_valor, rol=rol, nombre_mostrado=nombre_valor)


def ultimo_acceso_s(sesion: Mapping[str, object]) -> float | None:
    """Instante (época, segundos) del último acceso anotado; None si no hay."""
    valor = sesion.get(CLAVE_ULTIMO_ACCESO_S)
    if isinstance(valor, (int, float)):
        return float(valor)
    return None


def marcar_actividad(sesion: MutableMapping[str, object], momento_s: float) -> None:
    """Renueva el instante de actividad: la expiración es por inactividad (§7.3)."""
    sesion[CLAVE_ULTIMO_ACCESO_S] = momento_s
