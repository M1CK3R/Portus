"""Utilidades de prueba del núcleo web: aplicación temporal con relojes falsos (T-3)."""

from dataclasses import dataclass
from pathlib import Path

from flask import Flask

from pruebas.utilidades_pruebas import RelojUtcFalso
from web.aplicacion import crear_aplicacion
from web.configuracion.configuracion_web import ConfiguracionWeb
from web.modelos.usuario import Rol
from web.repositorios.conexion_bd import RUTA_ESQUEMA_POR_OMISION, ConexionBd
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.seguridad.hash_contrasenas import calcular_hash

CLAVE_SECRETA_DE_PRUEBA = "clave-fija-de-pruebas-no-es-secreto"
RONDAS_PRUEBA = 4
"""Rondas bcrypt mínimas: hash rápido y determinista para la suite (S-3 igual)."""


class RelojEpocaFalso:
    """Reloj de época inyectable para la expiración por inactividad (T-3)."""

    def __init__(self, inicial_s: float = 1_000_000.0) -> None:
        self._ahora_s = inicial_s

    def __call__(self) -> float:
        return self._ahora_s

    def avanzar_s(self, segundos: float) -> None:
        self._ahora_s += segundos


@dataclass
class WebPrueba:
    """Aplicación de prueba con sus relojes y su repositorio de usuarios."""

    app: Flask
    bd: ConexionBd
    usuarios: RepositorioUsuarios
    reloj_epoch: RelojEpocaFalso
    reloj_utc: RelojUtcFalso


def crear_web(tmp_path: Path) -> WebPrueba:
    """Construye una aplicación completa sobre una base temporal (BD-2 real)."""
    reloj_epoch = RelojEpocaFalso()
    reloj_utc = RelojUtcFalso()
    configuracion = ConfiguracionWeb(
        ruta_bd=str(tmp_path / "web_prueba.db"),
        ruta_esquema=str(RUTA_ESQUEMA_POR_OMISION),
        clave_secreta=CLAVE_SECRETA_DE_PRUEBA,
        puerto_web=0,
        expiracion_inactividad_min=30,
        vida_maxima_sesion_h=12,
        nivel_registro="ERROR",
    )
    bd = ConexionBd(configuracion.ruta_bd, configuracion.ruta_esquema)
    app = crear_aplicacion(configuracion, bd, reloj_epoch=reloj_epoch, fabrica_instante=reloj_utc)
    return WebPrueba(
        app=app,
        bd=bd,
        usuarios=RepositorioUsuarios(bd),
        reloj_epoch=reloj_epoch,
        reloj_utc=reloj_utc,
    )


def crear_usuario(web: WebPrueba, username: str, rol: Rol, contrasena: str) -> None:
    """Alta rápida de usuario de prueba con hash bcrypt de rondas mínimas."""
    creado = web.usuarios.crear(
        username=username,
        password_hash=calcular_hash(contrasena, rondas=RONDAS_PRUEBA),
        rol=rol,
        nombre_mostrado=username,
        creado_en="2026-09-20T14:03:22.418Z",
    )
    if not creado:
        mensaje = f"el usuario de prueba {username} ya existía"
        raise RuntimeError(mensaje)


def entrar(cliente: Flask.test_client, username: str, contrasena: str) -> object:
    """Inicia sesión por la API y devuelve la respuesta del servidor."""
    return cliente.post("/api/login", json={"username": username, "password": contrasena})
