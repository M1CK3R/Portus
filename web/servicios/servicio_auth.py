"""Autenticación con usuario y contraseña (SPECS §7.3; CODESTYLE S-3, S-5).

El servicio no conoce HTTP (A-2): recibe credenciales, consulta el
repositorio y devuelve un resultado tipado con el error exacto para que la
ruta decida el código HTTP y la auditoría. Los fallos de contraseña no
revelan si el usuario existe: el mismo mensaje para ambos casos (S-5) y una
verificación equivalente que iguala el tiempo de respuesta.
"""

import secrets
from dataclasses import dataclass

from web.modelos.usuario import Rol, Usuario
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.seguridad.hash_contrasenas import RONDAS_BCRYPT, calcular_hash, verificar_contrasena

ERROR_CREDENCIALES_INVALIDAS = "CREDENCIALES_INVALIDAS"
ERROR_SIN_ACCESO_WEB = "SIN_ACCESO_WEB"

MENSAJE_CREDENCIALES_INVALIDAS = "Usuario o contraseña incorrectos."
MENSAJE_SIN_ACCESO_WEB = (
    "El rol TRANSPORTISTA no tiene acceso web; opera únicamente por el canal de mensajería."
)

_HASH_EQUIVALENTE: str | None = None
"""Hash bcrypt de un valor aleatorio, generado una sola vez, para verificar
también cuando el usuario no existe: sin él, la respuesta llegaría antes y
un atacante podría distinguir usuarios existentes por el tiempo (S-5)."""


@dataclass(frozen=True)
class ResultadoAutenticacion:
    """Resultado del intento; ``usuario`` no es None solo si todo pasó."""

    usuario: Usuario | None
    error: str | None = None
    mensaje: str | None = None
    motivo_auditoria: str | None = None
    auditar: bool = False

    @property
    def autenticado(self) -> bool:
        return self.usuario is not None


class ServicioAuth:
    """Verifica credenciales contra los hashes bcrypt de la base (§7.3)."""

    def __init__(self, usuarios: RepositorioUsuarios) -> None:
        self._usuarios = usuarios

    def autenticar(self, username: str, contrasena: str) -> ResultadoAutenticacion:
        """Aplica el orden: existe → hash correcto → activo → rol con acceso web.

        Los tres primeros fallos responden el mismo mensaje genérico
        (``CREDENCIALES_INVALIDAS``); el último es una denegación de rol y
        por eso es explícita (§7.5.1). Todo fallo lleva su motivo exacto
        para la auditoría (§7.5.5).
        """
        par = self._usuarios.con_hash_por_username(username)
        if par is None:
            _verificacion_equivalente(contrasena)
            return ResultadoAutenticacion(
                usuario=None,
                error=ERROR_CREDENCIALES_INVALIDAS,
                mensaje=MENSAJE_CREDENCIALES_INVALIDAS,
                motivo_auditoria="usuario_desconocido",
                auditar=True,
            )
        usuario, hash_guardado = par
        if not verificar_contrasena(contrasena, hash_guardado):
            return ResultadoAutenticacion(
                usuario=None,
                error=ERROR_CREDENCIALES_INVALIDAS,
                mensaje=MENSAJE_CREDENCIALES_INVALIDAS,
                motivo_auditoria="contrasena_incorrecta",
                auditar=True,
            )
        if not usuario.activo:
            return ResultadoAutenticacion(
                usuario=None,
                error=ERROR_CREDENCIALES_INVALIDAS,
                mensaje=MENSAJE_CREDENCIALES_INVALIDAS,
                motivo_auditoria="usuario_inactivo",
                auditar=True,
            )
        if usuario.rol is Rol.TRANSPORTISTA:
            return ResultadoAutenticacion(
                usuario=None,
                error=ERROR_SIN_ACCESO_WEB,
                mensaje=MENSAJE_SIN_ACCESO_WEB,
                motivo_auditoria="rol_sin_acceso_web",
                auditar=True,
            )
        return ResultadoAutenticacion(usuario=usuario)


def _verificacion_equivalente(contrasena: str) -> None:
    """Gasta el mismo tiempo bcrypt que un usuario real para no filtrar por timing."""
    global _HASH_EQUIVALENTE
    if _HASH_EQUIVALENTE is None:
        _HASH_EQUIVALENTE = calcular_hash(secrets.token_urlsafe(24), rondas=RONDAS_BCRYPT)
    verificar_contrasena(contrasena, _HASH_EQUIVALENTE)
