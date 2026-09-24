"""Crea los 7 usuarios mínimos del SPECS §7.2 con hash bcrypt (§7.3, S-3).

Uso (SPECS §19.3 paso 4):
    python herramientas/crear_usuarios_semilla.py --bd db/portus.db

Las contraseñas se resuelven así, en orden: argumento ``--contrasena-<rol>``,
variable de entorno ``PORTUS_SEMILLA_<ROL>`` (por ejemplo en
``config/portus.env``) y, si no hay ninguna, se genera una aleatoria que se
imprime una sola vez al terminar. Los usernames son fijos para que la
documentación de credenciales (§7.2: «con credenciales en la documentación»)
sea estable entre despliegues. Ninguna contraseña queda en texto plano en la
base de datos: solo su hash bcrypt con sal (S-3).
"""

import argparse
import os
import secrets

from web.modelos.usuario import Rol
from web.repositorios.conexion_bd import ConexionBd
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.seguridad.hash_contrasenas import calcular_hash
from web.tiempo import marca_utc

PREFIJO_ENV = "PORTUS_SEMILLA_"

# (username, rol, nombre visible, opción CLI, variable de entorno). Los
# usuarios del mismo rol comparten contraseña: son credenciales de demostración.
SEMILLAS: list[tuple[str, Rol, str, str, str]] = [
    ("terminal01", Rol.TERMINAL, "Operador de terminal", "terminal", "TERMINAL"),
    ("naviera01", Rol.NAVIERA, "Naviera A", "naviera", "NAVIERA"),
    ("naviera02", Rol.NAVIERA, "Naviera B", "naviera", "NAVIERA"),
    ("agente01", Rol.AGENTE, "Agente aduanero", "agente", "AGENTE"),
    ("autoridad01", Rol.AUTORIDAD, "Autoridad aduanera", "autoridad", "AUTORIDAD"),
    (
        "transportista01",
        Rol.TRANSPORTISTA,
        "Transportista 1",
        "transportista",
        "TRANSPORTISTA",
    ),
    (
        "transportista02",
        Rol.TRANSPORTISTA,
        "Transportista 2",
        "transportista",
        "TRANSPORTISTA",
    ),
]


def _leer_argumentos() -> argparse.Namespace:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--bd", default="db/portus.db", help="ruta de la base SQLite")
    analizador.add_argument(
        "--esquema", default=None, help="ruta de db/esquema.sql (por omisión: la del repositorio)"
    )
    # Un único argumento por grupo de rol: los usuarios del mismo rol (dos
    # navieras, dos transportistas) comparten contraseña de demostración.
    for opcion in dict.fromkeys(opcion for _, _, _, opcion, _ in SEMILLAS):
        analizador.add_argument(f"--contrasena-{opcion}", default=None)
    return analizador.parse_args()


def _contrasena_de(nombre_rol: str, opcion: str, argumentos: argparse.Namespace) -> str:
    """Argumento CLI → variable de entorno → aleatoria impresa una vez (S-1)."""
    por_argumento = str(getattr(argumentos, f"contrasena_{opcion}") or "")
    if por_argumento not in ("", "None"):
        return por_argumento
    por_entorno = os.environ.get(f"{PREFIJO_ENV}{nombre_rol}")
    if por_entorno:
        return por_entorno
    return secrets.token_urlsafe(9)


def main() -> int:
    argumentos = _leer_argumentos()
    if argumentos.esquema is not None:
        bd = ConexionBd(argumentos.bd, argumentos.esquema)
    else:
        bd = ConexionBd(argumentos.bd)
    repositorio = RepositorioUsuarios(bd)
    ahora = marca_utc()
    credenciales: list[tuple[str, str]] = []
    try:
        for username, rol, nombre, opcion, nombre_rol in SEMILLAS:
            contrasena = _contrasena_de(nombre_rol, opcion, argumentos)
            creado = repositorio.crear(
                username=username,
                password_hash=calcular_hash(contrasena),
                rol=rol,
                nombre_mostrado=nombre,
                creado_en=ahora,
            )
            if creado:
                print(f"creado {username} ({rol.value})", flush=True)
                credenciales.append((username, contrasena))
            else:
                print(f"ya existía {username}; no se modifica", flush=True)
    finally:
        bd.cerrar()
    if credenciales:
        print("\nContraseñas asignadas (guárdelas ahora; no se vuelven a mostrar):", flush=True)
        for username, contrasena in credenciales:
            print(f"  {username}: {contrasena}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
