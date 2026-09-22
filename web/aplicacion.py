"""Fábrica de la aplicación Flask del núcleo web (SPECS §7, §18; CODESTYLE A-2).

La cookie de sesión se firma con la clave de ``portus.env`` (S-1) y viaja
``HttpOnly`` y ``SameSite=Lax`` (§7.3 [PROP]). El control de inactividad se
hace con un reloj inyectable (T-3): cada petición autenticada renueva el
instante y, si pasó el umbral, la sesión se cierra y la petición recibe 401
(JSON) o el formulario de login (páginas).
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

import flask
from flask import Flask

from web.configuracion.configuracion_web import ConfiguracionWeb
from web.contexto import (
    CLAVE_AUDITORIA,
    CLAVE_CONTEXTO,
    RELOJ_EPOCH_POR_OMISION,
    ContextoWeb,
    contexto,
    fabrica_instante_utc,
)
from web.repositorios.conexion_bd import ConexionBd
from web.repositorios.repositorio_auditoria import RepositorioAuditoria
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.repositorios.repositorio_vinculos import RepositorioVinculos
from web.rutas.rutas_api import crear_blueprint_api
from web.rutas.rutas_web import crear_blueprint_web
from web.seguridad.permisos import ERROR_SESION_EXPIRADA, Respuesta, respuesta_error
from web.seguridad.sesion import cerrar_sesion, marcar_actividad, ultimo_acceso_s, usuario_en_sesion
from web.servicios.servicio_auth import ServicioAuth
from web.servicios.servicio_vinculacion import ServicioVinculacion

REGISTRO = logging.getLogger(__name__)

NOMBRE_COOKIE_SESION = "portus_sesion"


def crear_aplicacion(
    configuracion: ConfiguracionWeb,
    bd: ConexionBd,
    reloj_epoch: Callable[[], float] = RELOJ_EPOCH_POR_OMISION,
    fabrica_instante: Callable[[], datetime] = fabrica_instante_utc,
) -> Flask:
    """Construye la aplicación con sus capas y sus reglas de sesión (§7.3)."""
    app = Flask(
        __name__,
        template_folder="interfaz/plantillas",
        static_folder="interfaz/estatico",
        static_url_path="/estatico",
    )
    app.secret_key = configuracion.clave_secreta
    app.config.update(
        SESSION_COOKIE_NAME=NOMBRE_COOKIE_SESION,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(seconds=configuracion.vida_maxima_sesion_s),
    )

    repositorio_auditoria = RepositorioAuditoria(bd)
    repositorio_usuarios = RepositorioUsuarios(bd)
    repositorio_vinculos = RepositorioVinculos(bd)
    contexto_web = ContextoWeb(
        usuarios=repositorio_usuarios,
        manifiestos=RepositorioManifiestos(bd),
        vinculos=repositorio_vinculos,
        auditoria=repositorio_auditoria,
        servicio_auth=ServicioAuth(repositorio_usuarios),
        servicio_vinculacion=ServicioVinculacion(
            vinculos=repositorio_vinculos,
            usuarios=repositorio_usuarios,
            fabrica_instante=fabrica_instante,
        ),
        configuracion=configuracion,
        reloj_epoch=reloj_epoch,
    )
    app.extensions[CLAVE_CONTEXTO] = contexto_web
    app.extensions[CLAVE_AUDITORIA] = repositorio_auditoria

    limite_inactividad_s = configuracion.expiracion_inactividad_s

    @app.before_request
    def controlar_inactividad() -> Respuesta | None:
        """Expira la sesión por inactividad y renueva el instante (§7.3)."""
        usuario = usuario_en_sesion(flask.session)
        if usuario is None:
            return None
        ahora_s = contexto().reloj_epoch()
        ultimo = ultimo_acceso_s(flask.session)
        if ultimo is not None and ahora_s - ultimo > limite_inactividad_s:
            cerrar_sesion(flask.session)
            REGISTRO.info("Sesión de %s expirada por inactividad (§7.3)", usuario.username)
            if flask.request.path.startswith("/api/"):
                return respuesta_error(
                    401, ERROR_SESION_EXPIRADA, "La sesión expiró por inactividad."
                )
            return flask.redirect("/login")
        marcar_actividad(flask.session, ahora_s)
        flask.session.permanent = True
        return None

    app.register_blueprint(crear_blueprint_api())
    app.register_blueprint(crear_blueprint_web())

    @app.errorhandler(404)
    def recurso_inexistente(error: object) -> Respuesta | tuple[str, int]:
        """S-5: error explícito sin detalles internos; JSON para la API."""
        if flask.request.path.startswith("/api/"):
            return respuesta_error(404, "RECURSO_INEXISTENTE", "La ruta no existe.")
        return flask.render_template("falta.html"), 404

    @app.errorhandler(405)
    def metodo_incorrecto(error: object) -> Respuesta:
        if flask.request.path.startswith("/api/"):
            return respuesta_error(405, "METODO_NO_PERMITIDO", "Método no permitido.")
        return flask.redirect("/login")

    @app.errorhandler(500)
    def fallo_interno(error: object) -> Respuesta:
        REGISTRO.error("Fallo interno no manejado: %s", error)
        return respuesta_error(500, "FALLO_INTERNO", "Fallo interno del servidor.")

    return app
