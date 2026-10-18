"""Hash de contraseñas con bcrypt y sal por usuario (SPECS §7.3, CODESTYLE S-3).

Las contraseñas nunca viven en texto plano en la base de datos ni en los
registros: solo su hash. ``bcrypt.checkpw`` compara en tiempo constante por
diseño del algoritmo.
"""

import logging

import bcrypt

REGISTRO = logging.getLogger(__name__)

RONDAS_BCRYPT = 12
"""Coste por omisión: ~250 ms por hash en hardware de servidor; en el SBC el
coste es aceptable porque solo se ejecuta al iniciar sesión y al crear
usuarios. Las pruebas usan rondas menores para ser rápidas y deterministas."""


def calcular_hash(contrasena: str, rondas: int = RONDAS_BCRYPT) -> str:
    """Genera el hash bcrypt con sal aleatoria; se guarda como texto UTF-8."""
    sal = bcrypt.gensalt(rounds=rondas)
    return bcrypt.hashpw(contrasena.encode("utf-8"), sal).decode("utf-8")


def verificar_contrasena(contrasena: str, hash_guardado: str) -> bool:
    """Compara la contraseña contra el hash guardado; False si el hash es corrupto."""
    try:
        return bcrypt.checkpw(contrasena.encode("utf-8"), hash_guardado.encode("utf-8"))
    except ValueError:
        # Un hash corrupto no debe tumbar el servicio ni revelar detalles (S-5).
        REGISTRO.warning("Hash de contraseña con formato inválido; se niega el acceso")
        return False
