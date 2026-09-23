"""Endpoints REST del núcleo (SPECS §18): sesión, vinculación, manifiestos,
turnos y retenciones.

Toda ruta exige sesión salvo ``/api/login`` (§18). Cada endpoint declara su
acción con ``@requiere_rol`` (PY-3): la matriz §7.4 se aplica en el servidor
y cualquier rechazo es explícito y auditado (§7.5). Las vistas viven a nivel
de módulo (A-4: complejidad acotada) y la fábrica solo las registra.
"""

from dataclasses import asdict

import flask
from flask import Blueprint

from web.contexto import contexto
from web.modelos.retencion import CausaRetencion, ResolucionRetencion, Retencion
from web.modelos.usuario import Rol, Usuario
from web.seguridad.permisos import (
    ACCION_EMITIR_COMANDO,
    ACCION_EXPORTAR_GRUA,
    ACCION_GENERAR_CODIGO_VINCULACION,
    ACCION_GENERAR_REPORTE,
    ACCION_GESTIONAR_CITAS,
    ACCION_GESTIONAR_PATIO,
    ACCION_GESTIONAR_TURNOS,
    ACCION_RECONOCER_ALARMA,
    ACCION_RESOLVER_RETENCION,
    ACCION_VER_GRUA,
    ACCION_VER_MANIFIESTOS,
    ACCION_VER_RETENCIONES,
    ACCION_VER_SINOPTICO,
    ACCION_VER_TURNOS,
    Respuesta,
    requiere_rol,
    requiere_sesion_json,
    respuesta_error,
)
from web.seguridad.sesion import cerrar_sesion, iniciar_sesion, usuario_en_sesion
from web.servicios.servicio_auth import ERROR_SIN_ACCESO_WEB, ResultadoAutenticacion
from web.servicios.servicio_retenciones import (
    ErrorMotivoRequerido,
    ErrorPermisoResolucion,
    ErrorRetencion,
    ErrorRetencionInexistente,
    ErrorRetencionResuelta,
)
from web.servicios.servicio_turnos import ErrorTransicion
from web.tiempo import marca_utc

ESTADOS_ACTIVOS = (
    "Programado",
    "EnGarita",
    "EnPesajeEntrada",
    "EnRuta",
    "EnTransferencia",
    "EnPesajeSalida",
    "EnSalida",
    "Retenido",
)
ESTADOS_HISTORICOS = ("Cerrado", "Anulado")


def crear_blueprint_api() -> Blueprint:
    """Construye el blueprint con los endpoints de las Etapas 4 y 5 (§18)."""
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
    api.add_url_rule("/api/turnos", view_func=turnos, methods=["GET"])
    api.add_url_rule("/api/turnos/<int:turno_id>", view_func=detalle_turno, methods=["GET"])
    api.add_url_rule(
        "/api/turnos/<int:turno_id>/retener", view_func=retener_turno, methods=["POST"]
    )
    api.add_url_rule("/api/turnos/<int:turno_id>/anular", view_func=anular_turno, methods=["POST"])
    api.add_url_rule("/api/retenciones", view_func=retenciones, methods=["GET"])
    api.add_url_rule(
        "/api/retenciones/<int:retencion_id>/aclarar", view_func=aclarar_retencion, methods=["POST"]
    )
    api.add_url_rule(
        "/api/retenciones/<int:retencion_id>/corregir",
        view_func=corregir_retencion,
        methods=["POST"],
    )
    api.add_url_rule(
        "/api/retenciones/<int:retencion_id>/rechazar",
        view_func=rechazar_retencion,
        methods=["POST"],
    )
    # Etapa 6 · TERMINAL (§14): sinóptico, patio, grúa, alarmas, citas, comandos, reportes.
    api.add_url_rule("/api/operacion", view_func=operacion, methods=["GET"])
    api.add_url_rule("/api/comandos/<nombre>", view_func=emitir_comando, methods=["POST"])
    api.add_url_rule("/api/patio", view_func=patio, methods=["GET"])
    api.add_url_rule(
        "/api/patio/posiciones/<posicion_id>/bloquear",
        view_func=bloquear_posicion,
        methods=["POST"],
    )
    api.add_url_rule(
        "/api/patio/posiciones/<posicion_id>/liberar",
        view_func=liberar_posicion,
        methods=["POST"],
    )
    api.add_url_rule("/api/grua", view_func=grua, methods=["GET"])
    api.add_url_rule("/api/grua/exportar", view_func=exportar_grua, methods=["GET"])
    api.add_url_rule("/api/alarmas", view_func=alarmas, methods=["GET"])
    api.add_url_rule(
        "/api/alarmas/<int:alarma_id>/reconocer", view_func=reconocer_alarma, methods=["POST"]
    )
    api.add_url_rule(
        "/api/alarmas/reconocer-todas", view_func=reconocer_todas_alarmas, methods=["POST"]
    )
    api.add_url_rule("/api/citas", view_func=citas, methods=["GET"])
    api.add_url_rule("/api/citas/<int:cita_id>/cancelar", view_func=cancelar_cita, methods=["POST"])
    api.add_url_rule(
        "/api/citas/<int:cita_id>/reprogramar", view_func=reprogramar_cita, methods=["POST"]
    )
    api.add_url_rule(
        "/api/franjas/<fecha>/<inicio>/bloquear", view_func=bloquear_franja, methods=["POST"]
    )
    api.add_url_rule("/api/transportistas", view_func=transportistas, methods=["GET"])
    api.add_url_rule("/api/reportes", view_func=generar_reporte, methods=["POST"])
    api.add_url_rule(
        "/api/reportes/<int:reporte_id>/exportar", view_func=exportar_reporte, methods=["GET"]
    )
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


# ------------------------------------------------------------ Etapa 5: turnos


@requiere_rol(ACCION_VER_TURNOS)
def turnos() -> Respuesta:
    """Listado de turnos con filtros (§14.2: estado, tipo, fecha, búsqueda)."""
    alcance = flask.request.args.get("alcance", "activos")
    estados = ESTADOS_HISTORICOS if alcance == "historicos" else ESTADOS_ACTIVOS
    filas = contexto().nucleo.listado.listar(
        estados,
        tipo_op=flask.request.args.get("tipo_op") or None,
        desde=flask.request.args.get("desde") or None,
        hasta=flask.request.args.get("hasta") or None,
        busqueda=flask.request.args.get("busqueda") or None,
    )
    return flask.jsonify({"turnos": [asdict(fila) for fila in filas]})


@requiere_rol(ACCION_VER_TURNOS)
def detalle_turno(turno_id: int) -> Respuesta:
    """Detalle del turno con su línea de tiempo completa (§14.2, §18)."""
    nucleo = contexto().nucleo
    turno = nucleo.maquina.buscar_turno(turno_id)
    if turno is None:
        return respuesta_error(404, "TURNO_INEXISTENTE", "No existe ese turno.")
    linea = nucleo.turnos_repo.linea_de_tiempo(turno.id)
    return flask.jsonify(
        {
            "turno": asdict(turno),
            "linea_de_tiempo": [asdict(evento) for evento in linea],
        }
    )


@requiere_rol(ACCION_GESTIONAR_TURNOS)
def retener_turno(turno_id: int) -> Respuesta:
    """Retención manual operativa RT06 del turno (TERMINAL, §10.2)."""
    datos = flask.request.get_json(silent=True) or {}
    if not isinstance(datos, dict):
        return respuesta_error(422, "CUERPO_INVALIDO", "Se espera un objeto JSON.")
    nucleo = contexto().nucleo
    turno = nucleo.maquina.buscar_turno(turno_id)
    if turno is None:
        return respuesta_error(404, "TURNO_INEXISTENTE", "No existe ese turno.")
    try:
        retenida = nucleo.retenciones_svc.retener(
            turno,
            CausaRetencion.RT06,
            "operacion",
            observacion=datos.get("observacion") or None,
        )
    except ErrorTransicion as error:
        return respuesta_error(409, "TRANSICION_NO_PERMITIDA", str(error))
    return _respuesta_retencion(retenida, 201)


@requiere_rol(ACCION_GESTIONAR_TURNOS)
def anular_turno(turno_id: int) -> Respuesta:
    """Anula el turno y autoriza la salida sin completar (TERMINAL, §8.2 regla 4, §8.6)."""
    datos = flask.request.get_json(silent=True) or {}
    if (
        not isinstance(datos, dict)
        or not isinstance(datos.get("motivo"), str)
        or not datos["motivo"].strip()
    ):
        return respuesta_error(422, "MOTIVO_REQUERIDO", "La anulación exige un motivo.")
    nucleo = contexto().nucleo
    turno = nucleo.maquina.buscar_turno(turno_id)
    if turno is None:
        return respuesta_error(404, "TURNO_INEXISTENTE", "No existe ese turno.")
    try:
        anulado = nucleo.maquina.anular(turno, datos["motivo"].strip(), "web")
    except ErrorTransicion as error:
        return respuesta_error(409, "TRANSICION_NO_PERMITIDA", str(error))
    if anulado.estado.value == "Anulado":
        nucleo.salida.autorizar_salida_anulacion(anulado)
    return flask.jsonify({"turno": asdict(anulado)})


# -------------------------------------------------------- Etapa 5: retenciones


@requiere_rol(ACCION_VER_RETENCIONES)
def retenciones() -> Respuesta:
    """Bandeja de retenciones: TERMINAL todas; AUTORIDAD solo aduaneras (§7.4)."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:  # no ocurre tras el decorador; defensa explícita
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    estado = flask.request.args.get("estado")
    if estado not in (None, "abierta", "resuelta"):
        return respuesta_error(422, "ESTADO_INVALIDO", "El estado debe ser abierta o resuelta.")
    causa = flask.request.args.get("causa")
    solo_aduaneras = usuario.rol is Rol.AUTORIDAD
    filas = contexto().nucleo.retenciones.listar(
        estado=estado, solo_aduaneras=solo_aduaneras, causa=causa
    )
    return flask.jsonify({"retenciones": [asdict(fila) for fila in filas]})


def _resolver(retencion_id: int, resolucion: ResolucionRetencion, motivo: str | None) -> Respuesta:
    """Aplica una resolución con el usuario en sesión y mapea los errores (§10.3)."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:  # no ocurre tras el decorador; defensa explícita
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    try:
        resuelta = contexto().nucleo.retenciones_svc.resolver(
            retencion_id,
            resolucion,
            usuario,
            motivo=motivo,
            observacion=(flask.request.get_json(silent=True) or {}).get("observacion") or None,
        )
    except ErrorRetencionInexistente as error:
        return respuesta_error(404, "RETENCION_INEXISTENTE", str(error))
    except ErrorRetencionResuelta as error:
        return respuesta_error(409, "RETENCION_RESUELTA", str(error))
    except ErrorPermisoResolucion as error:
        _auditar_resolucion_denegada(usuario, retencion_id, resolucion)
        return respuesta_error(403, "ACCION_NO_PERMITIDA", str(error))
    except ErrorMotivoRequerido as error:
        return respuesta_error(422, "MOTIVO_REQUERIDO", str(error))
    except ErrorRetencion as error:  # otros rechazos conocidos quedan explícitos
        return respuesta_error(409, "CONFLICTO_RETENCION", str(error))
    return _respuesta_retencion(resuelta, 200)


def _respuesta_retencion(retencion: Retencion, codigo: int) -> Respuesta:
    respuesta = flask.jsonify({"retencion": asdict(retencion)})
    respuesta.status_code = codigo
    return respuesta


def _auditar_resolucion_denegada(
    usuario: Usuario, retencion_id: int, resolucion: ResolucionRetencion
) -> None:
    """Deja constancia del 403 por causa no facultada (§7.5.5, D-6)."""
    contexto().auditoria.registrar(
        accion=f"resolver_retencion_{resolucion.value.lower()}",
        recurso=f"/api/retenciones/{retencion_id}",
        motivo="rol_no_facultado_causa",
        instante=marca_utc(),
        username=usuario.username,
        rol=usuario.rol.value,
    )


@requiere_rol(ACCION_RESOLVER_RETENCION)
def aclarar_retencion(retencion_id: int) -> Respuesta:
    """Aclarar: libera la plaza y regresa el turno a su estado previo (§10.3)."""
    return _resolver(retencion_id, ResolucionRetencion.ACLARAR, None)


@requiere_rol(ACCION_RESOLVER_RETENCION)
def corregir_retencion(retencion_id: int) -> Respuesta:
    """Corregir: peso declarado = medido; solo TERMINAL en RT01/RT02 (§10.3, A12)."""
    return _resolver(retencion_id, ResolucionRetencion.CORREGIR, None)


@requiere_rol(ACCION_RESOLVER_RETENCION)
def rechazar_retencion(retencion_id: int) -> Respuesta:
    """Rechazar: exige motivo, anula el turno y autoriza la salida (§10.3)."""
    datos = flask.request.get_json(silent=True) or {}
    motivo = datos.get("motivo") if isinstance(datos, dict) else None
    return _resolver(
        retencion_id, ResolucionRetencion.RECHAZAR, motivo if isinstance(motivo, str) else None
    )


# -------------------------------------------------------- Etapa 6: TERMINAL §14


@requiere_rol(ACCION_VER_SINOPTICO)
def operacion() -> Respuesta:
    """Snapshot inicial del sinóptico (§14.1); la actualización viva va por WebSocket."""
    nucleo = contexto().nucleo
    return flask.jsonify(
        {
            "plazas": [asdict(p) for p in nucleo.plazas.todas()],
            "posiciones": [asdict(p) for p in nucleo.patio.posiciones()],
            "celdas": [asdict(c) for c in nucleo.patio.celdas()],
        }
    )


@requiere_rol(ACCION_EMITIR_COMANDO)
def emitir_comando(nombre: str) -> Respuesta:
    """Emite un comando remoto del catálogo §6.1 y devuelve el ``cmd_id`` (§6.4).

    La confirmación de UI (si el comando la exige, §6.3) la pide el navegador
    antes de llamar aquí; la respuesta ACK/NAK llega por MQTT sobre WebSocket.
    """
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:  # no ocurre tras el decorador; defensa explícita
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    datos = flask.request.get_json(silent=True) or {}
    parametros = datos.get("parametros") if isinstance(datos, dict) else None
    if not isinstance(parametros, dict):
        parametros = {}
    cmd_id = contexto().nucleo.comandos_svc.emitir(nombre, parametros, usuario.username)
    return flask.jsonify({"cmd_id": cmd_id, "nombre": nombre})


@requiere_rol(ACCION_VER_SINOPTICO)
def patio() -> Respuesta:
    """Posiciones e inventario para la pestaña Patio (§12.2, §14.4)."""
    nucleo = contexto().nucleo
    return flask.jsonify(
        {
            "posiciones": [asdict(p) for p in nucleo.patio.posiciones()],
            "celdas": [asdict(c) for c in nucleo.patio.celdas()],
            "inventario": [asdict(f) for f in nucleo.patio.inventario_completo()],
        }
    )


@requiere_rol(ACCION_GESTIONAR_PATIO)
def bloquear_posicion(posicion_id: str) -> Respuesta:
    """Bloquea una posición del patio (§6.3 PosicionBloquear, §12.2)."""
    nucleo = contexto().nucleo
    if not nucleo.patio.bloquear_posicion(posicion_id):
        return respuesta_error(409, "POSICION_NO_LIBRE", "La posición no está libre para bloquear.")
    return flask.jsonify({"posicion": posicion_id, "estado": "bloqueada"})


@requiere_rol(ACCION_GESTIONAR_PATIO)
def liberar_posicion(posicion_id: str) -> Respuesta:
    """Libera el bloqueo de una posición (§6.3 PosicionLiberar, §12.2)."""
    nucleo = contexto().nucleo
    if not nucleo.patio.liberar_posicion(posicion_id):
        return respuesta_error(409, "POSICION_NO_BLOQUEADA", "La posición no está bloqueada.")
    return flask.jsonify({"posicion": posicion_id, "estado": "libre"})


@requiere_rol(ACCION_VER_GRUA)
def grua() -> Respuesta:
    """Estado de la grúa: trabajo en curso, cola y resumen (§12.6)."""
    nucleo = contexto().nucleo
    estado = nucleo.grua_svc.estado()
    return flask.jsonify(
        {
            "en_curso": estado["en_curso"],
            "cola_pendiente": estado["cola_pendiente"],
            "cantidad_pendiente": estado["cantidad_pendiente"],
            "fallas": [asdict(f) for f in nucleo.grua_svc.historial_fallas()],
        }
    )


@requiere_rol(ACCION_EXPORTAR_GRUA)
def exportar_grua() -> Respuesta:
    """Exporta el historial de ciclos de grúa en CSV del rango (§12.6)."""
    inicio = flask.request.args.get("inicio")
    fin = flask.request.args.get("fin")
    if not inicio or not fin:
        return respuesta_error(422, "RANGO_REQUERIDO", "Se requieren 'inicio' y 'fin'.")
    csv_texto = contexto().nucleo.grua_svc.exportar_csv(inicio, fin)
    respuesta = flask.make_response(csv_texto)
    respuesta.mimetype = "text/csv"
    respuesta.headers["Content-Disposition"] = "attachment; filename=historial_grua.csv"
    return respuesta


@requiere_rol(ACCION_RECONOCER_ALARMA)
def alarmas() -> Respuesta:
    """Listas de alarmas activas e históricas con filtro por severidad (§13.3)."""
    severidad = flask.request.args.get("severidad") or None
    nucleo = contexto().nucleo
    return flask.jsonify(
        {
            "activas": [asdict(a) for a in nucleo.alarmas_svc.activas(severidad=severidad)],
            "historicas": [asdict(a) for a in nucleo.alarmas_svc.historicas(severidad=severidad)],
        }
    )


@requiere_rol(ACCION_RECONOCER_ALARMA)
def reconocer_alarma(alarma_id: int) -> Respuesta:
    """Reconoce una alarma activa (§13.2); comentario opcional (§13.3)."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:  # no ocurre tras el decorador; defensa explícita
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    datos = flask.request.get_json(silent=True) or {}
    comentario = datos.get("comentario") if isinstance(datos, dict) else None
    comentario = comentario if isinstance(comentario, str) else None
    if not contexto().nucleo.alarmas_svc.reconocer(alarma_id, usuario.id, comentario):
        return respuesta_error(409, "ALARMA_NO_ACTIVA", "La alarma no está activa o no existe.")
    return flask.jsonify({"alarma": alarma_id, "estado": "reconocida"})


@requiere_rol(ACCION_RECONOCER_ALARMA)
def reconocer_todas_alarmas() -> Respuesta:
    """Reconoce en lote las alarmas de severidad baja y media (§13.3)."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:  # no ocurre tras el decorador; defensa explícita
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    cantidad = contexto().nucleo.alarmas_svc.reconocer_todas_baja_media(usuario.id)
    return flask.jsonify({"reconocidas": cantidad})


@requiere_rol(ACCION_GESTIONAR_CITAS)
def citas() -> Respuesta:
    """Agenda del día por franjas e indicador de cumplimiento (§14.5)."""
    fecha = flask.request.args.get("fecha")
    if not fecha:
        return respuesta_error(422, "FECHA_REQUERIDA", "Se requiere el parámetro 'fecha'.")
    nucleo = contexto().nucleo
    franjas = nucleo.citas_svc.agenda(fecha)
    cumplidas, total = nucleo.citas_svc.cumplimiento(fecha)
    return flask.jsonify(
        {
            "franjas": [asdict(f) for f in franjas],
            "cumplimiento": {
                "cumplidas_en_ventana": cumplidas,
                "total": total,
                "porcentaje": round(cumplidas / total * 100, 2) if total else 0.0,
            },
        }
    )


@requiere_rol(ACCION_GESTIONAR_CITAS)
def cancelar_cita(cita_id: int) -> Respuesta:
    """Cancela una cita programada y notifica al transportista (§11.4)."""
    if not contexto().nucleo.citas_svc.cancelar(cita_id):
        return respuesta_error(409, "CITA_NO_PROGRAMADA", "La cita no está programada.")
    return flask.jsonify({"cita": cita_id, "estado": "cancelada"})


@requiere_rol(ACCION_GESTIONAR_CITAS)
def reprogramar_cita(cita_id: int) -> Respuesta:
    """Reprograma una cita a otra franja con capacidad (§11.4, §14.5)."""
    datos = flask.request.get_json(silent=True) or {}
    if not isinstance(datos, dict):
        return respuesta_error(422, "CUERPO_INVALIDO", "Se espera un objeto JSON.")
    fecha = datos.get("fecha")
    inicio = datos.get("inicio")
    if not isinstance(fecha, str) or not isinstance(inicio, str):
        return respuesta_error(422, "FRANJA_REQUERIDA", "Se requieren 'fecha' e 'inicio'.")
    ok, motivo = contexto().nucleo.citas_svc.reprogramar(cita_id, fecha, inicio)
    if not ok:
        return respuesta_error(409, motivo or "REPROGRAMAR_FALLIDO", "No se pudo reprogramar.")
    return flask.jsonify({"cita": cita_id, "fecha": fecha, "inicio": inicio})


@requiere_rol(ACCION_GESTIONAR_CITAS)
def bloquear_franja(fecha: str, inicio: str) -> Respuesta:
    """Bloquea una franja para impedir nuevas citas (§11.4, §14.5)."""
    if not contexto().nucleo.citas_svc.bloquear_franja(fecha, inicio):
        return respuesta_error(404, "FRANJA_INEXISTENTE", "La franja no existe.")
    return flask.jsonify({"fecha": fecha, "inicio": inicio, "bloqueada": True})


@requiere_rol(ACCION_GENERAR_CODIGO_VINCULACION)
def transportistas() -> Respuesta:
    """Panel de vinculación de transportistas (§14.5, A17)."""
    filas = contexto().servicio_vinculacion.listar_panel_vinculacion()
    return flask.jsonify({"transportistas": [asdict(f) for f in filas]})


@requiere_rol(ACCION_GENERAR_REPORTE)
def generar_reporte() -> Respuesta:
    """Genera el reporte de corrida con las 8 métricas (§16.1, §16.3)."""
    datos = flask.request.get_json(silent=True) or {}
    if not isinstance(datos, dict):
        return respuesta_error(422, "CUERPO_INVALIDO", "Se espera un objeto JSON.")
    etiqueta = datos.get("etiqueta")
    inicio = datos.get("inicio")
    fin = datos.get("fin")
    if not isinstance(etiqueta, str) or not isinstance(inicio, str) or not isinstance(fin, str):
        return respuesta_error(
            422, "CAMPOS_REQUERIDOS", "Se requieren 'etiqueta', 'inicio' y 'fin'."
        )
    usuario = usuario_en_sesion(flask.session)
    reporte = contexto().nucleo.reportes_svc.generar(
        etiqueta=etiqueta,
        inicio=inicio,
        fin=fin,
        generado_por=usuario.id if usuario is not None else None,
    )
    return flask.jsonify({"reporte": asdict(reporte)})


@requiere_rol(ACCION_GENERAR_REPORTE)
def exportar_reporte(reporte_id: int) -> Respuesta:
    """Exporta el CSV con el detalle de cada turno del periodo (§16.3)."""
    nucleo = contexto().nucleo
    reporte = nucleo.reportes_repo.buscar_por_id(reporte_id)
    if reporte is None:
        return respuesta_error(404, "REPORTE_INEXISTENTE", "No existe ese reporte.")
    csv_texto = nucleo.reportes_svc.exportar_csv(reporte.inicio, reporte.fin)
    respuesta = flask.make_response(csv_texto)
    respuesta.mimetype = "text/csv"
    respuesta.headers["Content-Disposition"] = f"attachment; filename=reporte_{reporte_id}.csv"
    return respuesta
