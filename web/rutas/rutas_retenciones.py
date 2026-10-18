"""Endpoints de retenciones y parqueo (SPECS §10, §14.3, §14.9, §18; Etapa 8).

Bandeja con los campos de §14.3, las tres resoluciones con el rol facultado
comprobado en el servicio (§10.2, §10.3), las órdenes RT06 (TERMINAL) y RT05
(AUTORIDAD, A9), la anulación manual y «Liberar parqueo» (§6.3). Cada vista
declara su acción de la matriz §7.4 (PY-3) y no contiene reglas de negocio
(A-2): mapea la entrada y los errores del servicio a la respuesta exacta.
"""

from dataclasses import asdict

import flask
from flask import Blueprint

from web.contexto import contexto
from web.modelos.retencion import (
    CausaRetencion,
    FilaBandejaRetencion,
    ResolucionRetencion,
    Retencion,
)
from web.modelos.turno import ESTADOS_FINALES, EstadoTurno, puede_retenerse
from web.modelos.usuario import Usuario
from web.seguridad.permisos import (
    ACCION_CONSULTAR_CARGA,
    ACCION_EMITIR_COMANDO,
    ACCION_GESTIONAR_TURNOS,
    ACCION_ORDENAR_RETENCION_DOCUMENTAL,
    ACCION_RESOLVER_RETENCION,
    ACCION_VER_RETENCIONES,
    Respuesta,
    requiere_rol,
    respuesta_error,
)
from web.seguridad.sesion import usuario_en_sesion
from web.servicios.servicio_parqueo import ErrorPlazaParqueo
from web.servicios.servicio_retenciones import (
    ErrorCorreccionNoAplica,
    ErrorMotivoRequerido,
    ErrorOrdenRetencion,
    ErrorPermisoResolucion,
    ErrorRetencion,
    ErrorRetencionInexistente,
    ErrorRetencionResuelta,
)
from web.servicios.servicio_turnos import ErrorTransicion
from web.tiempo import marca_utc

ESTADOS_RETENCION = ("abierta", "resuelta")
ESTADOS_EN_CURSO = tuple(e.value for e in EstadoTurno if e not in ESTADOS_FINALES)
CODIGOS_HTTP_ORDEN = {
    "TURNO_INEXISTENTE": 404,
    "ROL_NO_FACULTADO": 403,
    "ESTADO_NO_RETENIBLE": 409,
    "RETENCION_ABIERTA": 409,
}


def registrar_rutas_retenciones(api: Blueprint) -> None:
    """Registra los endpoints de la Etapa 8 en el blueprint de la API (§18)."""
    api.add_url_rule("/api/retenciones", view_func=bandeja_retenciones, methods=["GET"])
    for resolucion, vista in (
        ("aclarar", aclarar_retencion),
        ("corregir", corregir_retencion),
        ("rechazar", rechazar_retencion),
    ):
        api.add_url_rule(
            f"/api/retenciones/<int:retencion_id>/{resolucion}", view_func=vista, methods=["POST"]
        )
    api.add_url_rule(
        "/api/turnos/<int:turno_id>/retener", view_func=retener_turno, methods=["POST"]
    )
    api.add_url_rule("/api/turnos/<int:turno_id>/anular", view_func=anular_turno, methods=["POST"])
    api.add_url_rule("/api/autoridad/turnos", view_func=turnos_para_autoridad, methods=["GET"])
    api.add_url_rule(
        "/api/autoridad/turnos/<int:turno_id>/retener",
        view_func=ordenar_retencion_documental,
        methods=["POST"],
    )
    api.add_url_rule(
        "/api/parqueo/<int:numero>/liberar", view_func=liberar_parqueo, methods=["POST"]
    )


# ------------------------------------------------------------------ bandeja


@requiere_rol(ACCION_VER_RETENCIONES)
def bandeja_retenciones() -> Respuesta:
    """Bandeja §14.3: TERMINAL todas; AUTORIDAD solo aduaneras (§7.4, §14.9)."""
    usuario = _usuario()
    estado = flask.request.args.get("estado") or None
    if estado is not None and estado not in ESTADOS_RETENCION:
        return respuesta_error(422, "ESTADO_INVALIDO", "El estado debe ser abierta o resuelta.")
    texto_causa = flask.request.args.get("causa") or None
    try:
        causa = CausaRetencion(texto_causa) if texto_causa is not None else None
    except ValueError:
        return respuesta_error(
            422, "CAUSA_INVALIDA", f"La causa debe ser RT01 a RT06 (recibido: {texto_causa})."
        )
    filas = contexto().nucleo.retenciones_svc.bandeja(usuario.rol, estado=estado, causa=causa)
    return flask.jsonify({"retenciones": [_fila_json(fila) for fila in filas]})


def _fila_json(fila: FilaBandejaRetencion) -> dict[str, object]:
    """Fila plana: los campos de la retención más los de §14.3."""
    return {
        **asdict(fila.retencion),
        "vehiculo": fila.vehiculo,
        "contenedor_id": fila.contenedor_id,
        "rol_facultado": fila.rol_facultado.value,
        "evidencia": asdict(fila.evidencia) if fila.evidencia is not None else None,
        "corregible": fila.corregible,
    }


# ------------------------------------------------------------- resoluciones


@requiere_rol(ACCION_RESOLVER_RETENCION)
def aclarar_retencion(retencion_id: int) -> Respuesta:
    """Aclarar: libera la plaza y regresa el turno a su estado previo (§10.3)."""
    return _resolver(retencion_id, ResolucionRetencion.ACLARAR)


@requiere_rol(ACCION_RESOLVER_RETENCION)
def corregir_retencion(retencion_id: int) -> Respuesta:
    """Corregir: peso declarado = medido; solo TERMINAL en RT01/RT02 (§10.3, A12)."""
    return _resolver(retencion_id, ResolucionRetencion.CORREGIR)


@requiere_rol(ACCION_RESOLVER_RETENCION)
def rechazar_retencion(retencion_id: int) -> Respuesta:
    """Rechazar: exige motivo, anula el turno y autoriza la salida (§10.3)."""
    return _resolver(retencion_id, ResolucionRetencion.RECHAZAR)


def _resolver(retencion_id: int, resolucion: ResolucionRetencion) -> Respuesta:
    """Aplica una resolución con el usuario en sesión y mapea los errores (§10.3)."""
    usuario = _usuario()
    cuerpo = _cuerpo()
    try:
        resuelta = contexto().nucleo.retenciones_svc.resolver(
            retencion_id,
            resolucion,
            usuario,
            motivo=_texto(cuerpo, "motivo"),
            observacion=_texto(cuerpo, "observacion"),
        )
    except ErrorRetencionInexistente as error:
        return respuesta_error(404, "RETENCION_INEXISTENTE", str(error))
    except ErrorRetencionResuelta as error:
        return respuesta_error(409, "RETENCION_RESUELTA", str(error))
    except ErrorPermisoResolucion as error:
        _auditar_denegada(usuario, f"resolver_retencion_{resolucion.value.lower()}")
        return respuesta_error(403, "ACCION_NO_PERMITIDA", str(error))
    except ErrorMotivoRequerido as error:
        return respuesta_error(422, "MOTIVO_REQUERIDO", str(error))
    except ErrorCorreccionNoAplica as error:
        return respuesta_error(409, "CORREGIR_NO_APLICA", str(error))
    except ErrorRetencion as error:  # otros rechazos conocidos quedan explícitos
        return respuesta_error(409, "CONFLICTO_RETENCION", str(error))
    return _respuesta_retencion(resuelta, 200)


# ------------------------------------------------------------------ órdenes


@requiere_rol(ACCION_GESTIONAR_TURNOS)
def retener_turno(turno_id: int) -> Respuesta:
    """Retención manual operativa RT06 del turno (TERMINAL, §10.2)."""
    return _ordenar(turno_id, CausaRetencion.RT06, _texto(_cuerpo(), "observacion"))


@requiere_rol(ACCION_ORDENAR_RETENCION_DOCUMENTAL)
def ordenar_retencion_documental(turno_id: int) -> Respuesta:
    """Retención documental RT05 ordenada por la autoridad desde Consulta de carga (A9)."""
    motivo = _texto(_cuerpo(), "motivo")
    if motivo is None:
        return respuesta_error(422, "MOTIVO_REQUERIDO", "La retención documental exige motivo.")
    return _ordenar(turno_id, CausaRetencion.RT05, motivo)


def _ordenar(turno_id: int, causa: CausaRetencion, nota: str | None) -> Respuesta:
    usuario = _usuario()
    try:
        retenida = contexto().nucleo.retenciones_svc.ordenar(turno_id, causa, usuario, nota)
    except ErrorOrdenRetencion as error:
        if error.codigo == "ROL_NO_FACULTADO":
            _auditar_denegada(usuario, f"ordenar_{causa.value.lower()}")
        return respuesta_error(CODIGOS_HTTP_ORDEN.get(error.codigo, 409), error.codigo, str(error))
    except ErrorTransicion as error:
        return respuesta_error(409, "TRANSICION_NO_PERMITIDA", str(error))
    return _respuesta_retencion(retenida, 201)


@requiere_rol(ACCION_CONSULTAR_CARGA)
def turnos_para_autoridad() -> Respuesta:
    """Turnos en curso con su contenedor para ordenar RT05 (§14.9, A9)."""
    filas = contexto().nucleo.listado.listar(
        estados=ESTADOS_EN_CURSO, busqueda=flask.request.args.get("busqueda") or None
    )
    return flask.jsonify(
        {
            "turnos": [
                {
                    "id": fila.id,
                    "estado": fila.estado,
                    "tipo_op": fila.tipo_op,
                    "vehiculo": fila.identificador_vehiculo,
                    "contenedor_id": fila.contenedor_id,
                    "creado_en": fila.creado_en,
                    "retenible": puede_retenerse(fila.estado),
                }
                for fila in filas
            ]
        }
    )


@requiere_rol(ACCION_GESTIONAR_TURNOS)
def anular_turno(turno_id: int) -> Respuesta:
    """Anula el turno y autoriza la salida sin completar (TERMINAL, §8.2 regla 4, §8.6)."""
    motivo = _texto(_cuerpo(), "motivo")
    if motivo is None:
        return respuesta_error(422, "MOTIVO_REQUERIDO", "La anulación exige un motivo.")
    try:
        anulado = contexto().nucleo.retenciones_svc.anular_turno(turno_id, motivo)
    except ErrorOrdenRetencion as error:
        return respuesta_error(CODIGOS_HTTP_ORDEN.get(error.codigo, 409), error.codigo, str(error))
    except ErrorTransicion as error:
        return respuesta_error(409, "TRANSICION_NO_PERMITIDA", str(error))
    return flask.jsonify({"turno": asdict(anulado)})


# ------------------------------------------------------------------ parqueo


@requiere_rol(ACCION_EMITIR_COMANDO)
def liberar_parqueo(numero: int) -> Respuesta:
    """«Liberar parqueo»: AgujaLiberar de una plaza ocupada con retención resuelta (§6.3)."""
    usuario = _usuario()
    try:
        cmd_id = contexto().nucleo.parqueo_svc.liberar_parqueo(numero, usuario.username)
    except ErrorPlazaParqueo as error:
        codigo = 404 if error.codigo == "PLAZA_INEXISTENTE" else 409
        return respuesta_error(codigo, error.codigo, str(error))
    respuesta = flask.jsonify(
        {"plaza": numero, "cmd_id": cmd_id, "nombre": "AgujaLiberar", "estado": "pendiente"}
    )
    respuesta.status_code = 202
    return respuesta


# ------------------------------------------------------------------ apoyo


def _usuario() -> Usuario:
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:  # no ocurre tras @requiere_rol; defensa explícita (D-10)
        flask.abort(401)
    return usuario


def _cuerpo() -> dict[str, object]:
    datos = flask.request.get_json(silent=True)
    return datos if isinstance(datos, dict) else {}


def _texto(cuerpo: dict[str, object], clave: str) -> str | None:
    """Texto recortado del cuerpo JSON; None si falta, no es texto o queda vacío."""
    valor = cuerpo.get(clave)
    return valor.strip() or None if isinstance(valor, str) else None


def _respuesta_retencion(retencion: Retencion, codigo: int) -> Respuesta:
    respuesta = flask.jsonify({"retencion": asdict(retencion)})
    respuesta.status_code = codigo
    return respuesta


def _auditar_denegada(usuario: Usuario, accion: str) -> None:
    """Deja constancia del 403 por causa no facultada (§7.5.5, D-6)."""
    contexto().auditoria.registrar(
        accion=accion,
        recurso=flask.request.path,
        motivo="rol_no_facultado_causa",
        instante=marca_utc(),
        username=usuario.username,
        rol=usuario.rol.value,
    )
