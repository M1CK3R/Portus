"""Páginas del núcleo: login, shell con pestañas por rol y logout (SPECS §7.3, §7.6).

El nombre del usuario y su rol se renderizan en el servidor en la cabecera
de todas las páginas (§7.3.3: visibles de forma permanente), y la
navegación muestra únicamente las pestañas del rol (§7.6). Las vistas viven
a nivel de módulo (A-4) y la fábrica solo las registra.
"""

import flask
from flask import Blueprint

from web.contexto import contexto
from web.modelos.pestanas import ETIQUETA_ETAPA_POR_SLUG, pestana_por_slug, pestanas_de_rol
from web.modelos.usuario import Rol, Usuario
from web.seguridad.permisos import Respuesta, requiere_sesion_html
from web.seguridad.sesion import iniciar_sesion, usuario_en_sesion
from web.servicios.servicio_auth import ERROR_SIN_ACCESO_WEB
from web.tiempo import marca_utc


def crear_blueprint_web() -> Blueprint:
    """Construye el blueprint de páginas del núcleo."""
    paginas = Blueprint("web", __name__)
    paginas.add_url_rule("/", view_func=inicio, methods=["GET"])
    paginas.add_url_rule("/login", view_func=formulario_login, methods=["GET"])
    paginas.add_url_rule("/login", view_func=enviar_login, methods=["POST"])
    paginas.add_url_rule("/logout", view_func=logout, methods=["GET"])
    paginas.add_url_rule("/pestanas/<slug>", view_func=panel, methods=["GET"])
    return paginas


@requiere_sesion_html
def inicio() -> Respuesta:
    """Redirige a la primera pestaña del rol en sesión (§7.6)."""
    usuario = _usuario_o_login()
    if isinstance(usuario, Respuesta):
        return usuario
    pestanas = pestanas_de_rol(usuario.rol)
    if not pestanas:  # TRANSPORTISTA jamás llega: el login lo rechaza (§7.1)
        return flask.redirect("/login")
    return flask.redirect(f"/pestanas/{pestanas[0].slug}")


def formulario_login() -> Respuesta | str:
    """Formulario de acceso (§18: única ruta pública junto a sus estáticos)."""
    if usuario_en_sesion(flask.session) is not None:
        return flask.redirect("/")
    return flask.render_template("login.html")


def enviar_login() -> Respuesta | tuple[str, int]:
    """Procesa el formulario; el error es explícito y auditado (§7.5.5)."""
    username = flask.request.form.get("username", "")
    contrasena = flask.request.form.get("password", "")
    if not username.strip() or not contrasena:
        return flask.render_template("login.html", error="Complete usuario y contraseña."), 422
    ctx = contexto()
    resultado = ctx.servicio_auth.autenticar(username.strip(), contrasena)
    if resultado.usuario is None:
        if resultado.auditar:
            ctx.auditoria.registrar(
                accion="iniciar_sesion",
                recurso="/login",
                motivo=resultado.motivo_auditoria or "desconocido",
                instante=marca_utc(),
                username=username.strip(),
            )
        return flask.render_template(
            "login.html", error=resultado.mensaje or "No se pudo iniciar sesión."
        ), (403 if resultado.error == ERROR_SIN_ACCESO_WEB else 401)
    iniciar_sesion(flask.session, resultado.usuario, ctx.reloj_epoch())
    flask.session.permanent = True
    return flask.redirect("/")


@requiere_sesion_html
def logout() -> Respuesta:
    """Cierre de sesión explícito con redirección al formulario (§7.3)."""
    flask.session.clear()
    return flask.redirect("/login")


@requiere_sesion_html
def panel(slug: str) -> Respuesta:
    """Panel de una pestaña del rol; un slug ajeno responde 404 (§7.6)."""
    usuario = _usuario_o_login()
    if isinstance(usuario, Respuesta):
        return usuario
    activa = pestana_por_slug(usuario.rol, slug)
    if activa is None:
        return flask.abort(404)
    return flask.make_response(
        flask.render_template(
            "panel.html",
            usuario=usuario,
            pestanas=pestanas_de_rol(usuario.rol),
            activa=activa,
            etiqueta_etapa=ETIQUETA_ETAPA_POR_SLUG.get(slug, "Etapa posterior"),
        )
    )


def _usuario_o_login() -> Usuario | Respuesta:
    """Usuario de la sesión o la redirección al login; helper de las páginas."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:
        return flask.redirect("/login")
    if usuario.rol is Rol.TRANSPORTISTA:
        # El login ya lo rechaza; si una sesión vieja quedara viva, se corta aquí.
        flask.session.clear()
        return flask.redirect("/login")
    return usuario
