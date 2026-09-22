"""Endpoints REST del núcleo (SPECS §18): sesión, vinculación y manifiestos.

Toda ruta exige sesión salvo ``/api/login`` (§18). Cada endpoint declara su
acción con ``@requiere_rol`` (PY-3): la matriz §7.4 se aplica en el servidor
y cualquier rechazo es explícito y auditado (§7.5). Las vistas viven a nivel
de módulo (A-4: complejidad acotada) y la fábrica solo las registra.
"""

from dataclasses import asdict

import flask
from flask import Blueprint

from web.contexto import contexto
from web.modelos.usuario import Rol
from web.seguridad.permisos import (
    ACCION_GENERAR_CODIGO_VINCULACION,
    ACCION_VER_MANIFIESTOS,
    Respuesta,
    requiere_rol,
    requiere_sesion_json,
    respuesta_error,
)
from web.seguridad.sesion import cerrar_sesion, iniciar_sesion, usuario_en_sesion
from web.servicios.servicio_auth import ERROR_SIN_ACCESO_WEB, ResultadoAutenticacion
from web.tiempo import marca_utc


def crear_blueprint_api() -> Blueprint:
    """Construye el blueprint con los endpoints de la Etapa 4 (§18)."""
    api = Blueprint("api", __name__)
    api.add_url_rule("/api/login", view_func=login, methods=["POST"])
    api.add_url_rule("/api/logout", view_func=logout, methods=["POST"])
    api.add_url_rule("/api/sesion", view_func=sesion, methods=["GET"])
    api.add_url_rule(
        "/api/transportistas/<int:id_transportista>/codigo-vinculacion",
        view_func=generar_codigo_vinculacion,
        methods=["POST"],
    )
    api.add_url_rule("/api/manifiestos", view_func=manifiestos, methods=["GET"])
    return api


def login() -> Respuesta:
    """Inicia sesión (§18: única ruta pública). Cuerpo JSON: username, password."""
    datos = flask.request.get_json(silent=True)
    if not isinstance(datos, dict):
        return respuesta_error(422, "CUERPO_INVALIDO", "Se espera un objeto JSON.")
    username = datos.get("username")
    contrasena = datos.get("password")
    if not isinstance(username, str) or not isinstance(contrasena, str):
        return respuesta_error(
            422, "CAMPO_FALTANTE", "Se requieren los campos 'username' y 'password'."
        )
    if not username.strip() or not contrasena:
        return respuesta_error(
            422, "CAMPO_VACIO", "'username' y 'password' no pueden quedar vacíos."
        )
    ctx = contexto()
    resultado = ctx.servicio_auth.autenticar(username.strip(), contrasena)
    if resultado.usuario is None:
        return _registrar_fallo_login(username.strip(), resultado)
    iniciar_sesion(flask.session, resultado.usuario, ctx.reloj_epoch())
    flask.session.permanent = True
    return flask.jsonify(
        {
            "username": resultado.usuario.username,
            "rol": resultado.usuario.rol.value,
            "nombre_mostrado": resultado.usuario.nombre_mostrado,
        }
    )


def _registrar_fallo_login(username: str, resultado: ResultadoAutenticacion) -> Respuesta:
    """Audita el intento fallido (§7.5.5) y responde 401 o 403 según la causa."""
    if resultado.auditar:
        contexto().auditoria.registrar(
            accion="iniciar_sesion",
            recurso=flask.request.path,
            motivo=resultado.motivo_auditoria or "desconocido",
            instante=marca_utc(),
            username=username,
        )
    codigo = 403 if resultado.error == ERROR_SIN_ACCESO_WEB else 401
    return respuesta_error(
        codigo,
        resultado.error or "ERROR_AUTENTICACION",
        resultado.mensaje or "No se pudo iniciar sesión.",
    )


@requiere_sesion_json
def logout() -> Respuesta:
    """Cierre de sesión explícito (§7.3)."""
    cerrar_sesion(flask.session)
    return flask.jsonify({"ok": True})


@requiere_sesion_json
def sesion() -> Respuesta:
    """Nombre y rol del usuario en sesión, para mostrarlos de forma permanente (§7.3)."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:  # no ocurre tras el decorador; defensa explícita
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    return flask.jsonify(
        {
            "username": usuario.username,
            "rol": usuario.rol.value,
            "nombre_mostrado": usuario.nombre_mostrado,
        }
    )


@requiere_rol(ACCION_GENERAR_CODIGO_VINCULACION)
def generar_codigo_vinculacion(id_transportista: int) -> Respuesta:
    """Genera el código de vinculación de un transportista (§15.1, A17).

    Solo TERMINAL (§7.4). El código es de 6 caracteres, de un solo uso y
    vence a los 60 minutos; invalida el activo anterior del transportista.
    """
    codigo = contexto().servicio_vinculacion.generar(id_transportista)
    if codigo is None:
        # 404 tanto si no existe como si el id no es transportista (§7.5.2).
        # No es un rechazo de permiso (el rol sí puede), pero se audita
        # igual (§7.5.5, D-6): la repetición de estos intentos delata
        # sondeo de identificadores sobre un endpoint que entrega
        # credenciales de acceso.
        _auditar_transportista_inexistente()
        return respuesta_error(
            404,
            "TRANSPORTISTA_INEXISTENTE",
            "No existe un transportista con ese identificador.",
        )
    return flask.jsonify({"codigo": codigo.codigo, "expira_en": codigo.expira_en})


def _auditar_transportista_inexistente() -> None:
    """Deja constancia del 404 en ``auditoria_rechazo`` (D-6: error en silencio, ninguno)."""
    usuario = usuario_en_sesion(flask.session)
    contexto().auditoria.registrar(
        accion="generar_codigo_vinculacion",
        recurso=flask.request.path,
        motivo="transportista_inexistente",
        instante=marca_utc(),
        username=usuario.username if usuario else None,
        rol=usuario.rol.value if usuario else None,
    )


@requiere_rol(ACCION_VER_MANIFIESTOS)
def manifiestos() -> Respuesta:
    """Listado con filtro de propiedad en SQL para NAVIERA (§7.4, §7.5.2)."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:  # no ocurre tras el decorador; defensa explícita
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    # Filtro de propiedad: NAVIERA ve solo lo suyo dentro de la consulta SQL
    # (§7.5.2); TERMINAL, AGENTE y AUTORIDAD ven el listado completo (§7.4).
    naviera_id = usuario.id if usuario.rol is Rol.NAVIERA else None
    filas = contexto().manifiestos.listar(naviera_id=naviera_id)
    return flask.jsonify({"manifiestos": [asdict(fila) for fila in filas]})
