"""Endpoints de reportes de corrida (SPECS §16.3, §14.6, §18; Etapa 12).

Generar con rango y etiqueta, listar y recuperar los reportes guardados, y
exportar sus dos CSV (detalle por turno y resumen de métricas). Solo TERMINAL
(§7.4 «Generar reporte»). El rango inválido o invertido responde 422 con la
causa exacta; las rutas no calculan nada (A-2).
"""

from dataclasses import asdict

import flask
from flask import Blueprint

from web.contexto import contexto
from web.modelos.reporte import ErrorRango, Reporte
from web.seguridad.permisos import (
    ACCION_GENERAR_REPORTE,
    Respuesta,
    requiere_rol,
    respuesta_error,
)
from web.seguridad.sesion import usuario_en_sesion
from web.servicios.exportacion_reportes import csv_detalle, csv_metricas

CONTENIDO_DETALLE = "detalle"
CONTENIDO_METRICAS = "metricas"


def registrar_rutas_reportes(api: Blueprint) -> None:
    api.add_url_rule("/api/reportes", view_func=generar_reporte, methods=["POST"])
    api.add_url_rule("/api/reportes", view_func=listar_reportes, methods=["GET"])
    api.add_url_rule("/api/reportes/<int:reporte_id>", view_func=ver_reporte, methods=["GET"])
    api.add_url_rule(
        "/api/reportes/<int:reporte_id>/exportar", view_func=exportar_reporte, methods=["GET"]
    )


@requiere_rol(ACCION_GENERAR_REPORTE)
def generar_reporte() -> Respuesta:
    """Calcula y guarda las 8 métricas del rango (§16.1, §16.3)."""
    datos = flask.request.get_json(silent=True) or {}
    if not isinstance(datos, dict):
        return respuesta_error(422, "CUERPO_INVALIDO", "Se espera un objeto JSON.")
    etiqueta = datos.get("etiqueta", "")
    inicio = datos.get("inicio")
    fin = datos.get("fin")
    if not isinstance(etiqueta, str) or not isinstance(inicio, str) or not isinstance(fin, str):
        return respuesta_error(
            422, "CAMPOS_REQUERIDOS", "Se requieren 'etiqueta', 'inicio' y 'fin'."
        )
    usuario = usuario_en_sesion(flask.session)
    try:
        reporte = contexto().nucleo.reportes_svc.generar(
            etiqueta=etiqueta,
            inicio=inicio,
            fin=fin,
            generado_por=usuario.id if usuario is not None else None,
        )
    except ErrorRango as error:
        return respuesta_error(422, error.codigo, str(error))
    return flask.jsonify({"reporte": asdict(reporte)})


@requiere_rol(ACCION_GENERAR_REPORTE)
def listar_reportes() -> Respuesta:
    """Reportes guardados, del más reciente al más antiguo (§16.3 [PROP])."""
    reportes = contexto().nucleo.reportes_svc.recientes()
    return flask.jsonify({"reportes": [asdict(reporte) for reporte in reportes]})


@requiere_rol(ACCION_GENERAR_REPORTE)
def ver_reporte(reporte_id: int) -> Respuesta:
    reporte = contexto().nucleo.reportes_svc.buscar(reporte_id)
    if reporte is None:
        return _inexistente()
    return flask.jsonify({"reporte": asdict(reporte)})


@requiere_rol(ACCION_GENERAR_REPORTE)
def exportar_reporte(reporte_id: int) -> Respuesta:
    """CSV del reporte: ``?contenido=detalle`` (por turno, §16.3) o ``metricas``."""
    servicio = contexto().nucleo.reportes_svc
    reporte = servicio.buscar(reporte_id)
    if reporte is None:
        return _inexistente()
    contenido = flask.request.args.get("contenido", CONTENIDO_DETALLE)
    if contenido == CONTENIDO_DETALLE:
        texto = csv_detalle(reporte, servicio.detalle_de_turnos(reporte))
    elif contenido == CONTENIDO_METRICAS:
        texto = csv_metricas(reporte)
    else:
        return respuesta_error(
            422, "CONTENIDO_INVALIDO", "El contenido debe ser 'detalle' o 'metricas'."
        )
    return _adjunto_csv(texto, _nombre_de_archivo(reporte, contenido))


def _nombre_de_archivo(reporte: Reporte, contenido: str) -> str:
    return f"reporte_{reporte.id}_{contenido}_{reporte.politica.lower()}.csv"


def _adjunto_csv(texto: str, nombre: str) -> Respuesta:
    respuesta = flask.make_response(texto)
    respuesta.mimetype = "text/csv"
    respuesta.headers["Content-Disposition"] = f"attachment; filename={nombre}"
    return respuesta


def _inexistente() -> Respuesta:
    return respuesta_error(404, "REPORTE_INEXISTENTE", "No existe ese reporte.")
