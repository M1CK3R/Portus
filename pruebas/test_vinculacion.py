"""Pruebas del código de vinculación: §15.1 y A17 (endpoint de la Etapa 4).

Generación solo por TERMINAL, 6 caracteres sin ambiguos, vigencia de 60
minutos, invalidación del anterior y un solo uso. El consumo se prueba con
el servicio (la pantalla llega en la Etapa 6 y el bot en la Etapa 10).
"""

import pytest

from pruebas.utilidades_web import crear_usuario, crear_web, entrar
from web.modelos.usuario import Rol
from web.servicios.servicio_vinculacion import ALFABETO_CODIGO, LONGITUD_CODIGO

CONTRASENA = "clave-vinculo-123"


@pytest.fixture()
def web(tmp_path):
    web_prueba = crear_web(tmp_path)
    crear_usuario(web_prueba, "terminal01", Rol.TERMINAL, CONTRASENA)
    crear_usuario(web_prueba, "naviera01", Rol.NAVIERA, CONTRASENA)
    crear_usuario(web_prueba, "transportista01", Rol.TRANSPORTISTA, CONTRASENA)
    crear_usuario(web_prueba, "transportista02", Rol.TRANSPORTISTA, CONTRASENA)
    yield web_prueba
    web_prueba.bd.cerrar()


def _id_transportista(web, username: str) -> int:
    return web.usuarios.con_hash_por_username(username)[0].id


def _ruta_transportista(web, username: str) -> str:
    """URL del endpoint de vinculación del transportista dado."""
    return f"/api/transportistas/{_id_transportista(web, username)}/codigo-vinculacion"


def test_terminal_genera_codigo_de_seis_caracteres_sin_ambiguos(web):
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    ruta = _ruta_transportista(web, "transportista01")
    respuesta = cliente.post(ruta)
    assert respuesta.status_code == 200
    cuerpo = respuesta.get_json()
    codigo = cuerpo["codigo"]
    assert len(codigo) == LONGITUD_CODIGO
    assert all(caracter in ALFABETO_CODIGO for caracter in codigo)
    assert not any(caracter in "0O1IL" for caracter in codigo)


def test_la_vigencia_del_codigo_es_de_60_minutos_sobre_el_reloj_inyectado(web):
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    ruta = _ruta_transportista(web, "transportista01")
    respuesta = cliente.post(ruta)
    cuerpo = respuesta.get_json()
    from web.tiempo import instante_de_marca

    vigencia = instante_de_marca(cuerpo["expira_en"]) - web.reloj_utc()
    assert vigencia.total_seconds() == 60 * 60


def test_generar_un_codigo_nuevo_invalide_el_anterior_del_mismo_transportista(web):
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    ruta = f"/api/transportistas/{_id_transportista(web, 'transportista01')}/codigo-vinculacion"
    primero = cliente.post(ruta).get_json()["codigo"]
    segundo = cliente.post(ruta).get_json()["codigo"]
    assert primero != segundo
    servicio = web.app.extensions["contexto_portus"].servicio_vinculacion
    assert servicio.consumir(primero) is None  # invalidado (§15.1)
    transportista = servicio.consumir(segundo)
    assert transportista is not None
    assert transportista.rol is Rol.TRANSPORTISTA


def test_cada_transportista_tiene_su_propio_codigo_independiente(web):
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    ruta_1 = f"/api/transportistas/{_id_transportista(web, 'transportista01')}/codigo-vinculacion"
    ruta_2 = f"/api/transportistas/{_id_transportista(web, 'transportista02')}/codigo-vinculacion"
    codigo_1 = cliente.post(ruta_1).get_json()["codigo"]
    codigo_2 = cliente.post(ruta_2).get_json()["codigo"]
    servicio = web.app.extensions["contexto_portus"].servicio_vinculacion
    consumido_1 = servicio.consumir(codigo_1)
    assert consumido_1 is not None and consumido_1.username == "transportista01"
    consumido_2 = servicio.consumir(codigo_2)
    assert consumido_2 is not None and consumido_2.username == "transportista02"


def test_el_codigo_es_de_un_solo_uso(web):
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    ruta = _ruta_transportista(web, "transportista01")
    respuesta = cliente.post(ruta)
    codigo = respuesta.get_json()["codigo"]
    servicio = web.app.extensions["contexto_portus"].servicio_vinculacion
    assert servicio.consumir(codigo) is not None
    assert servicio.consumir(codigo) is None  # ya quedó usado (§15.1)


def test_el_codigo_expira_a_los_60_minutos(web):
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    ruta = _ruta_transportista(web, "transportista01")
    respuesta = cliente.post(ruta)
    codigo = respuesta.get_json()["codigo"]
    web.reloj_utc.avanzar_ms(61 * 60 * 1000)
    servicio = web.app.extensions["contexto_portus"].servicio_vinculacion
    assert servicio.consumir(codigo) is None


def test_identificador_de_transportista_inexistente_responde_404(web):
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    respuesta = cliente.post("/api/transportistas/9999/codigo-vinculacion")
    assert respuesta.status_code == 404
    assert respuesta.get_json()["error"] == "TRANSPORTISTA_INEXISTENTE"


def test_el_404_por_transportista_inexistente_queda_auditado(web):
    # D-6: el rechazo no queda en silencio; va a auditoria_rechazo (§7.5.5).
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    cliente.post("/api/transportistas/9999/codigo-vinculacion")
    rechazos = web.app.extensions["contexto_portus"].auditoria.ultimos(1)
    assert len(rechazos) == 1
    rechazo = rechazos[0]
    assert rechazo.accion == "generar_codigo_vinculacion"
    assert rechazo.motivo == "transportista_inexistente"
    assert rechazo.recurso == "/api/transportistas/9999/codigo-vinculacion"
    assert rechazo.username == "terminal01"
    assert rechazo.rol == "TERMINAL"


def test_el_404_por_id_que_no_es_transportista_tambien_queda_auditado(web):
    # Mismo registro sin revelar en el motivo cuál de las dos causas fue (§7.5.2).
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    id_naviera = _id_transportista(web, "naviera01")
    cliente.post(f"/api/transportistas/{id_naviera}/codigo-vinculacion")
    rechazo = web.app.extensions["contexto_portus"].auditoria.ultimos(1)[0]
    assert rechazo.motivo == "transportista_inexistente"
    assert rechazo.username == "terminal01"


def test_identificador_de_un_rol_que_no_es_transportista_responde_404(web):
    # No se revela si el id existe y no es transportista o no existe (§7.5.2).
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    id_naviera = _id_transportista(web, "naviera01")
    respuesta = cliente.post(f"/api/transportistas/{id_naviera}/codigo-vinculacion")
    assert respuesta.status_code == 404
    assert respuesta.get_json()["error"] == "TRANSPORTISTA_INEXISTENTE"


def test_el_codigo_se_consumo_con_minisculas_y_espacios(web):
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    ruta = _ruta_transportista(web, "transportista01")
    respuesta = cliente.post(ruta)
    codigo = respuesta.get_json()["codigo"]
    servicio = web.app.extensions["contexto_portus"].servicio_vinculacion
    consumido = servicio.consumir(f"  {codigo.lower()} ")
    assert consumido is not None and consumido.username == "transportista01"
