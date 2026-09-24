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
from web.modelos.alarma import Severidad
from web.modelos.reporte import ErrorRango, normalizar_rango
from web.modelos.usuario import Rol
from web.rutas.rutas_reportes import registrar_rutas_reportes
from web.rutas.rutas_retenciones import registrar_rutas_retenciones
from web.seguridad.permisos import (
    ACCION_ANULAR_MANIFIESTO,
    ACCION_CONSULTAR_CARGA,
    ACCION_CREAR_MANIFIESTO,
    ACCION_EMITIR_COMANDO,
    ACCION_EXPORTAR_GRUA,
    ACCION_GENERAR_CODIGO_VINCULACION,
    ACCION_GESTIONAR_CITAS,
    ACCION_GESTIONAR_PATIO,
    ACCION_OTORGAR_LEVANTE,
    ACCION_PRESENTAR_DECLARACION,
    ACCION_RECONOCER_ALARMA,
    ACCION_SOLICITAR_LEVANTE,
    ACCION_VER_CONTENEDORES_PROPIOS,
    ACCION_VER_GRUA,
    ACCION_VER_MANIFIESTOS,
    ACCION_VER_SEGUIMIENTO,
    ACCION_VER_SINOPTICO,
    ACCION_VER_TURNOS,
    Respuesta,
    requiere_rol,
    requiere_sesion_json,
    respuesta_error,
)
from web.seguridad.sesion import cerrar_sesion, iniciar_sesion, usuario_en_sesion
from web.servicios.servicio_alarmas import ErrorAlarma
from web.servicios.servicio_alarmas import catalogo as catalogo_alarmas
from web.servicios.servicio_auth import ERROR_SIN_ACCESO_WEB, ResultadoAutenticacion
from web.servicios.servicio_comandos import ErrorComando
from web.servicios.servicio_patio import ErrorPosicion
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
    _registrar_etapa7(api)
    registrar_rutas_retenciones(api)
    registrar_rutas_reportes(api)
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


# -------------------------------------------------------- Etapa 6: TERMINAL §14


@requiere_rol(ACCION_VER_SINOPTICO)
def operacion() -> Respuesta:
    """Snapshot inicial del sinóptico (§14.1); la actualización viva va por WebSocket."""
    nucleo = contexto().nucleo
    return flask.jsonify(
        {
            "plazas": nucleo.parqueo_svc.estado(),
            "posiciones": [asdict(p) for p in nucleo.patio.posiciones()],
            "celdas": [asdict(c) for c in nucleo.patio.celdas()],
            "alarmas_activas": nucleo.alarmas_svc.cantidad_activas(),
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
    parametros_texto = {str(clave): str(valor) for clave, valor in parametros.items()}
    try:
        cmd_id = contexto().nucleo.comandos_svc.emitir(nombre, parametros_texto, usuario.username)
    except ErrorComando as error:
        # §6.3: no disponible en el estado actual → 409; solicitud mal formada → 422.
        codigo_http = 409 if error.codigo == "COMANDO_NO_DISPONIBLE" else 422
        return respuesta_error(codigo_http, error.codigo, str(error))
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
    """Envía PosicionBloquear; la BD cambia solo con el ACK del controlador (§6.1, §6.3)."""
    return _comando_posicion(posicion_id, bloquear=True)


@requiere_rol(ACCION_GESTIONAR_PATIO)
def liberar_posicion(posicion_id: str) -> Respuesta:
    """Envía PosicionLiberar (solo si está bloqueada); aplica con el ACK (§6.3)."""
    return _comando_posicion(posicion_id, bloquear=False)


def _comando_posicion(posicion_id: str, bloquear: bool) -> Respuesta:
    """202 con el ``cmd_id``: el resultado real llega como ACK/NAK por MQTT (§6.2)."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:  # no ocurre tras el decorador; defensa explícita
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    patio = contexto().nucleo.patio
    solicitar = patio.solicitar_bloqueo if bloquear else patio.solicitar_liberacion
    try:
        cmd_id = solicitar(posicion_id, usuario.username)
    except ErrorPosicion as error:
        codigo = 404 if error.codigo == "POSICION_INEXISTENTE" else 409
        return respuesta_error(codigo, error.codigo, str(error))
    respuesta = flask.jsonify({"posicion": posicion_id, "cmd_id": cmd_id, "estado": "pendiente"})
    respuesta.status_code = 202
    return respuesta


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
    try:
        # El rango llega en hora de la terminal; los ciclos están en UTC (Etapa 12).
        desde, hasta = normalizar_rango(inicio, fin)
    except ErrorRango as error:
        return respuesta_error(422, error.codigo, str(error))
    csv_texto = contexto().nucleo.grua_svc.exportar_csv(desde, hasta)
    respuesta = flask.make_response(csv_texto)
    respuesta.mimetype = "text/csv"
    respuesta.headers["Content-Disposition"] = "attachment; filename=historial_grua.csv"
    return respuesta


@requiere_rol(ACCION_RECONOCER_ALARMA)
def alarmas() -> Respuesta:
    """Activas, históricas (filtro por severidad) y el catálogo §13.1 (§13.3)."""
    severidad = flask.request.args.get("severidad") or None
    if severidad is not None and severidad not in {s.value for s in Severidad}:
        return respuesta_error(
            422,
            "SEVERIDAD_INVALIDA",
            f"Severidad CRITICA, ALTA, MEDIA o BAJA (recibido: {severidad}).",
        )
    nucleo = contexto().nucleo
    return flask.jsonify(
        {
            "activas": [asdict(a) for a in nucleo.alarmas_svc.activas(severidad=severidad)],
            "historicas": [asdict(a) for a in nucleo.alarmas_svc.historicas(severidad=severidad)],
            "catalogo": catalogo_alarmas(),
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
    comentario = comentario.strip() or None if isinstance(comentario, str) else None
    try:
        alarma = contexto().nucleo.alarmas_svc.reconocer(
            alarma_id, usuario.id, usuario.username, comentario
        )
    except ErrorAlarma as error:
        return respuesta_error(409, "ALARMA_NO_ACTIVA", str(error))
    return flask.jsonify({"alarma": asdict(alarma)})


@requiere_rol(ACCION_RECONOCER_ALARMA)
def reconocer_todas_alarmas() -> Respuesta:
    """Reconoce en lote las alarmas de severidad baja y media (§13.3)."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:  # no ocurre tras el decorador; defensa explícita
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    cantidad = contexto().nucleo.alarmas_svc.reconocer_todas_baja_media(
        usuario.id, usuario.username
    )
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
    ok, motivo = contexto().nucleo.citas_svc.cancelar(cita_id)
    if not ok:
        return _error_de_cita(motivo)
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
        return _error_de_cita(motivo)
    return flask.jsonify({"cita": cita_id, "fecha": fecha, "inicio": inicio})


@requiere_rol(ACCION_GESTIONAR_CITAS)
def bloquear_franja(fecha: str, inicio: str) -> Respuesta:
    """Bloquea una franja, exista o no todavía, para impedir nuevas citas (§11.4, §14.5)."""
    if not contexto().nucleo.citas_svc.bloquear_franja(fecha, inicio):
        return _error_de_cita("FRANJA_INVALIDA")
    return flask.jsonify({"fecha": fecha, "inicio": inicio, "bloqueada": True})


ERRORES_DE_CITA: dict[str, tuple[int, str]] = {
    "CITA_INEXISTENTE": (404, "No existe esa cita."),
    "CITA_EN_USO": (409, "El vehículo ya ingresó con esta cita; su desenlace lo decide el turno."),
    "CITA_NO_PROGRAMADA": (409, "La cita no está programada."),
    "FRANJA_INVALIDA": (422, "La franja debe ser aaaa-mm-dd y HH:MM en múltiplos de 15 min."),
    "FRANJA_PASADA": (409, "Solo se puede reprogramar a una franja futura."),
    "FRANJA_BLOQUEADA": (409, "La franja está bloqueada."),
    "FRANJA_SIN_CAPACIDAD": (409, "La franja ya tiene 2 citas."),
}
"""Motivo del servicio de citas → (HTTP, mensaje explícito sin detalles internos, S-5)."""


def _error_de_cita(motivo: str) -> Respuesta:
    codigo, mensaje = ERRORES_DE_CITA.get(motivo, (409, "No se pudo completar la acción."))
    return respuesta_error(codigo, motivo or "ACCION_FALLIDA", mensaje)


@requiere_rol(ACCION_GENERAR_CODIGO_VINCULACION)
def transportistas() -> Respuesta:
    """Panel de vinculación de transportistas (§14.5, A17)."""
    filas = contexto().servicio_vinculacion.listar_panel_vinculacion()
    return flask.jsonify({"transportistas": [asdict(f) for f in filas]})


# -------------------------------------------------- Etapa 7: NAVIERA §14.7


@requiere_rol(ACCION_CREAR_MANIFIESTO)
def crear_manifiesto() -> Respuesta:
    """NAVIERA crea un manifiesto con validaciones (§9.3, §14.7)."""
    datos = flask.request.get_json(silent=True) or {}
    if not isinstance(datos, dict):
        return respuesta_error(422, "CUERPO_INVALIDO", "Se espera un objeto JSON.")
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    ok, resultado = contexto().servicio_manifiestos.crear(
        naviera_id=usuario.id,
        contenedor_id=str(datos.get("contenedor_id", "")),
        tipo_op=str(datos.get("tipo_op", "")),
        peso_declarado_g=int(datos.get("peso_declarado_g", 0)),
        tolerancia_pct=int(datos.get("tolerancia_pct", 5)),
        transportista_id=int(datos.get("transportista_id", 0)),
        observaciones=str(datos.get("observaciones", "")),
    )
    if not ok:
        return respuesta_error(409, str(resultado), "No se pudo crear el manifiesto.")
    return flask.jsonify({"manifiesto_id": resultado})


@requiere_rol(ACCION_VER_MANIFIESTOS)
def detalle_manifiesto(manifiesto_id: int) -> Respuesta:
    """Detalle del manifiesto con historial (§14.7); NAVIERA solo los propios (§7.4)."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:  # no ocurre tras el decorador; defensa explícita
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    servicio = contexto().servicio_manifiestos
    naviera_id = usuario.id if usuario.rol is Rol.NAVIERA else None
    detalle = servicio.detalle(manifiesto_id, naviera_id)
    if detalle is None:
        if naviera_id is not None and servicio.existe(manifiesto_id):
            # [DEC §7.5.2] 403 y no 404: el aislamiento entre navieras se
            # demuestra en la evaluación y el rechazo queda auditado (§7.5.5).
            contexto().auditoria.registrar(
                accion="ver_manifiesto",
                recurso=flask.request.path,
                motivo="manifiesto_de_otra_naviera",
                instante=marca_utc(),
                username=usuario.username,
                rol=usuario.rol.value,
            )
            return respuesta_error(
                403, "ACCION_NO_PERMITIDA", "El manifiesto pertenece a otra naviera."
            )
        return respuesta_error(404, "MANIFIESTO_INEXISTENTE", "No existe ese manifiesto.")
    return flask.jsonify(
        {
            "manifiesto": asdict(detalle.manifiesto),
            "historial": [asdict(h) for h in detalle.historial],
        }
    )


@requiere_rol(ACCION_ANULAR_MANIFIESTO)
def anular_manifiesto(manifiesto_id: int) -> Respuesta:
    """Anula el manifiesto solo si no tiene turno (§14.7)."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    if not contexto().servicio_manifiestos.anular(manifiesto_id, usuario.id):
        return respuesta_error(409, "NO_ANULABLE", "El manifiesto ya tiene turno o no es suyo.")
    return flask.jsonify({"manifiesto": manifiesto_id, "estado": "anulado"})


@requiere_rol(ACCION_VER_CONTENEDORES_PROPIOS)
def contenedores_propios() -> Respuesta:
    """Contenedores de la naviera en sesión (§14.7, aislamiento §7.5.2)."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    filas = contexto().servicio_manifiestos.mis_contenedores(usuario.id)
    return flask.jsonify({"contenedores": [asdict(f) for f in filas]})


# -------------------------------------------------- Etapa 7: AGENTE §14.8


@requiere_rol(ACCION_PRESENTAR_DECLARACION)
def bandeja_declaraciones() -> Respuesta:
    """Manifiestos sin levante para el AGENTE (§14.8)."""
    filas = contexto().servicio_declaraciones.bandeja_sin_levante()
    return flask.jsonify({"manifiestos": [asdict(f) for f in filas]})


@requiere_rol(ACCION_PRESENTAR_DECLARACION)
def presentar_declaracion() -> Respuesta:
    """Presenta la declaración de mercancías (§9.3, §14.8)."""
    datos = flask.request.get_json(silent=True) or {}
    if not isinstance(datos, dict):
        return respuesta_error(422, "CUERPO_INVALIDO", "Se espera un objeto JSON.")
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    from web.modelos.declaracion import Regimen

    try:
        regimen = Regimen(str(datos.get("regimen", "")))
    except ValueError:
        return respuesta_error(422, "REGIMEN_INVALIDO", "Régimen no reconocido (§9.3).")
    ok, resultado = contexto().servicio_declaraciones.presentar(
        agente_id=usuario.id,
        manifiesto_id=int(datos.get("manifiesto_id", 0)),
        numero=str(datos.get("numero", "")),
        regimen=regimen,
        descripcion=str(datos.get("descripcion", "")),
        valor=int(datos.get("valor", 0)),
    )
    if not ok:
        return respuesta_error(409, str(resultado), "No se pudo presentar la declaración.")
    return flask.jsonify({"declaracion_id": resultado})


@requiere_rol(ACCION_SOLICITAR_LEVANTE)
def solicitar_levante(manifiesto_id: int) -> Respuesta:
    """Solicita el levante (solo con declaración presentada) (§9.1, §14.8)."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    ok, resultado = contexto().servicio_declaraciones.solicitar_levante(usuario.id, manifiesto_id)
    if not ok:
        return respuesta_error(409, str(resultado), "No se pudo solicitar el levante.")
    return flask.jsonify({"levante_id": resultado})


@requiere_rol(ACCION_SOLICITAR_LEVANTE)
def adjuntar_observacion(manifiesto_id: int) -> Respuesta:
    """Adjunta una observación visible para la AUTORIDAD (§14.8)."""
    datos = flask.request.get_json(silent=True) or {}
    observacion = datos.get("observacion", "") if isinstance(datos, dict) else ""
    if not str(observacion).strip():
        return respuesta_error(422, "OBSERVACION_REQUERIDA", "La observación no puede estar vacía.")
    contexto().servicio_declaraciones.adjuntar_observacion(manifiesto_id, str(observacion))
    return flask.jsonify({"manifiesto": manifiesto_id, "observacion": str(observacion)})


@requiere_rol(ACCION_VER_SEGUIMIENTO)
def seguimiento_agente() -> Respuesta:
    """Estado de las solicitudes del agente (§14.8)."""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    from web.repositorios.repositorio_levantes import RepositorioLevantes

    repo = RepositorioLevantes(contexto().nucleo.turnos_repo._bd)
    filas = repo.seguimiento_de_agente(usuario.id)
    return flask.jsonify({"solicitudes": [asdict(f) for f in filas]})


# -------------------------------------------------- Etapa 7: AUTORIDAD §14.9


@requiere_rol(ACCION_OTORGAR_LEVANTE)
def levantes_pendientes() -> Respuesta:
    """Bandeja de solicitudes de levante pendientes (§14.9)."""
    filas = contexto().servicio_levantes.pendientes()
    return flask.jsonify({"solicitudes": [asdict(f) for f in filas]})


@requiere_rol(ACCION_OTORGAR_LEVANTE)
def otorgar_levante(levante_id: int) -> Respuesta:
    """Otorga el levante con canal verde/rojo (§9.1, §9.2)."""
    datos = flask.request.get_json(silent=True) or {}
    canal = datos.get("canal", "") if isinstance(datos, dict) else ""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    ok, causa = contexto().servicio_levantes.otorgar(levante_id, str(canal), usuario.id)
    if not ok:
        return respuesta_error(409, causa, "No se pudo otorgar el levante.")
    return flask.jsonify({"levante": levante_id, "estado": "otorgada", "canal": str(canal)})


@requiere_rol(ACCION_OTORGAR_LEVANTE)
def retener_levante(levante_id: int) -> Respuesta:
    """Retiene el levante con motivo (§9.1, §9.2)."""
    datos = flask.request.get_json(silent=True) or {}
    motivo = datos.get("motivo", "") if isinstance(datos, dict) else ""
    usuario = usuario_en_sesion(flask.session)
    if usuario is None:
        return respuesta_error(401, "SESION_REQUERIDA", "Inicie sesión.")
    ok, causa = contexto().servicio_levantes.retener(levante_id, str(motivo), usuario.id)
    if not ok:
        return respuesta_error(409, causa, "No se pudo retener el levante.")
    return flask.jsonify({"levante": levante_id, "estado": "retenida", "motivo": str(motivo)})


@requiere_rol(ACCION_OTORGAR_LEVANTE)
def ver_declaracion(levante_id: int) -> Respuesta:
    """Ver la declaración de mercancías del levante (§14.9)."""
    decl = contexto().servicio_levantes.ver_declaracion(levante_id)
    if decl is None:
        return respuesta_error(
            404, "DECLARACION_INEXISTENTE", "No hay declaración para ese levante."
        )
    return flask.jsonify({"declaracion": asdict(decl)})


@requiere_rol(ACCION_CONSULTAR_CARGA)
def consulta_carga() -> Respuesta:
    """Consulta de carga: cualquier contenedor (§14.9)."""
    contenedor_id = flask.request.args.get("contenedor_id") or None
    filas = contexto().servicio_levantes.consulta_carga(contenedor_id)
    return flask.jsonify({"contenedores": [asdict(f) for f in filas]})


# -------------------------------------------------- Registro Etapa 7


def _registrar_etapa7(api: Blueprint) -> None:
    """Registra los endpoints de la Etapa 7 (NAVIERA/AGENTE/AUTORIDAD)."""
    api.add_url_rule("/api/manifiestos", view_func=crear_manifiesto, methods=["POST"])
    api.add_url_rule(
        "/api/manifiestos/<int:manifiesto_id>/detalle",
        view_func=detalle_manifiesto,
        methods=["GET"],
    )
    api.add_url_rule(
        "/api/manifiestos/<int:manifiesto_id>/anular", view_func=anular_manifiesto, methods=["POST"]
    )
    api.add_url_rule("/api/naviera/contenedores", view_func=contenedores_propios, methods=["GET"])
    api.add_url_rule("/api/declaraciones", view_func=bandeja_declaraciones, methods=["GET"])
    api.add_url_rule(
        "/api/declaraciones/presentar", view_func=presentar_declaracion, methods=["POST"]
    )
    api.add_url_rule(
        "/api/manifiestos/<int:manifiesto_id>/solicitar-levante",
        view_func=solicitar_levante,
        methods=["POST"],
    )
    api.add_url_rule(
        "/api/manifiestos/<int:manifiesto_id>/observacion",
        view_func=adjuntar_observacion,
        methods=["POST"],
    )
    api.add_url_rule("/api/agente/seguimiento", view_func=seguimiento_agente, methods=["GET"])
    api.add_url_rule("/api/levantes", view_func=levantes_pendientes, methods=["GET"])
    api.add_url_rule(
        "/api/levantes/<int:levante_id>/otorgar", view_func=otorgar_levante, methods=["POST"]
    )
    api.add_url_rule(
        "/api/levantes/<int:levante_id>/retener", view_func=retener_levante, methods=["POST"]
    )
    api.add_url_rule(
        "/api/levantes/<int:levante_id>/declaracion", view_func=ver_declaracion, methods=["GET"]
    )
    api.add_url_rule("/api/autoridad/consulta-carga", view_func=consulta_carga, methods=["GET"])
