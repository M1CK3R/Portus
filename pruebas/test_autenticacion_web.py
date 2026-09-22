"""Pruebas de autenticación y sesión: §7.3 y §18 (login, logout, inactividad)."""

import pytest

from pruebas.utilidades_pruebas import INSTANTE_FIJO
from pruebas.utilidades_web import crear_usuario, crear_web, entrar
from web.modelos.usuario import Rol

CONTRASENA = "clave-servicio-123"


@pytest.fixture()
def web(tmp_path):
    """Aplicación web de prueba sobre una base SQLite temporal."""
    web_prueba = crear_web(tmp_path)
    crear_usuario(web_prueba, "terminal01", Rol.TERMINAL, CONTRASENA)
    crear_usuario(web_prueba, "naviera01", Rol.NAVIERA, CONTRASENA)
    crear_usuario(web_prueba, "transportista01", Rol.TRANSPORTISTA, CONTRASENA)
    yield web_prueba
    web_prueba.bd.cerrar()


def test_login_valido_devuelve_rol_y_cookie_con_banderas_de_sesion(web):
    cliente = web.app.test_client()
    respuesta = cliente.post("/api/login", json={"username": "terminal01", "password": CONTRASENA})
    assert respuesta.status_code == 200
    cuerpo = respuesta.get_json()
    assert cuerpo["username"] == "terminal01"
    assert cuerpo["rol"] == "TERMINAL"
    # §7.3 [PROP]: cookie de sesión firmada, HttpOnly y SameSite=Lax.
    cookies = ", ".join(respuesta.headers.getlist("Set-Cookie"))
    assert "HttpOnly" in cookies
    assert "SameSite=Lax" in cookies


def test_login_con_hash_bcrypt_en_la_base_no_en_texto_plano(web):
    with web.bd.candado:
        fila = web.bd.conexion.execute(
            "SELECT password_hash FROM usuario WHERE username = 'terminal01'"
        ).fetchone()
    hash_guardado = str(fila[0])
    # S-3: nunca texto plano; formato bcrypt con sal ($2b$).
    assert hash_guardado != CONTRASENA
    assert hash_guardado.startswith("$2")


def test_login_con_contrasena_incorrecta_responde_401_generico(web):
    cliente = web.app.test_client()
    respuesta = cliente.post("/api/login", json={"username": "terminal01", "password": "mala"})
    assert respuesta.status_code == 401
    assert respuesta.get_json()["error"] == "CREDENCIALES_INVALIDAS"


def test_login_de_usuario_desconocido_dara_el_mismo_error_que_contrasena_mala(web):
    # S-5: el mensaje no revela si el usuario existe.
    cliente = web.app.test_client()
    respuesta = cliente.post("/api/login", json={"username": "nadie", "password": CONTRASENA})
    assert respuesta.status_code == 401
    assert respuesta.get_json()["error"] == "CREDENCIALES_INVALIDAS"


def test_login_de_usuario_inactivo_responde_401_y_audita_el_motivo_exacto(web):
    web.usuarios.cambiar_activo("naviera01", activo=False)
    cliente = web.app.test_client()
    respuesta = cliente.post("/api/login", json={"username": "naviera01", "password": CONTRASENA})
    assert respuesta.status_code == 401
    assert respuesta.get_json()["error"] == "CREDENCIALES_INVALIDAS"
    # El usuario sigue existiendo; solo se deshabilitó (no se oculta al auditor).
    assert web.usuarios.con_hash_por_username("naviera01") is not None
    rechazos = web.app.extensions["repositorio_auditoria"].ultimos(1)
    assert rechazos[0].motivo == "usuario_inactivo"


def test_login_de_transportista_se_rechaza_con_403_explicito_por_no_tener_web(web):
    # §7.1: TRANSPORTISTA opera solo por mensajería; §7.5.1: denegación explícita.
    cliente = web.app.test_client()
    respuesta = cliente.post(
        "/api/login", json={"username": "transportista01", "password": CONTRASENA}
    )
    assert respuesta.status_code == 403
    cuerpo = respuesta.get_json()
    assert cuerpo["error"] == "SIN_ACCESO_WEB"
    assert "mensajería" in cuerpo["mensaje"]


def test_login_con_cuerpo_malformado_responde_422(web):
    cliente = web.app.test_client()
    assert cliente.post("/api/login", data="no-json", content_type="text/plain").status_code == 422
    assert cliente.post("/api/login", json={"username": "solo-usuario"}).status_code == 422
    assert cliente.post("/api/login", json={"username": "", "password": "x"}).status_code == 422


def test_sesion_sin_iniciar_responde_401_y_con_sesion_devuelve_rol(web):
    cliente = web.app.test_client()
    respuesta_sin_sesion = cliente.get("/api/sesion")
    assert respuesta_sin_sesion.status_code == 401
    assert respuesta_sin_sesion.get_json()["error"] == "SESION_REQUERIDA"
    entrar(cliente, "terminal01", CONTRASENA)
    respuesta = cliente.get("/api/sesion")
    assert respuesta.status_code == 200
    assert respuesta.get_json()["rol"] == "TERMINAL"


def test_logout_cierra_la_sesion_de_forma_explicita(web):
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    assert cliente.post("/api/logout").status_code == 200
    respuesta = cliente.get("/api/sesion")
    assert respuesta.status_code == 401


def test_sesion_expira_por_inactividad_con_umbral_de_30_minutos(web):
    # §7.3: expiración por inactividad; T-3: reloj inyectado, sin sleep.
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    web.reloj_epoch.avanzar_s(29 * 60)
    assert cliente.get("/api/sesion").status_code == 200  # renovó la actividad
    web.reloj_epoch.avanzar_s(31 * 60)
    respuesta = cliente.get("/api/sesion")
    assert respuesta.status_code == 401
    assert respuesta.get_json()["error"] == "SESION_EXPIRADA"


def test_la_pagina_de_login_es_publica_y_la_raiz_redirige_sin_sesion(web):
    cliente = web.app.test_client()
    respuesta_login = cliente.get("/login")
    assert respuesta_login.status_code == 200
    assert b"Iniciar sesi" in respuesta_login.data
    respuesta_raiz = cliente.get("/")
    assert respuesta_raiz.status_code == 302
    assert respuesta_raiz.headers["Location"].endswith("/login")


def test_fabrica_de_instante_inyectada_da_marcas_deterministas(web):
    # El reloj UTC falso arranca en INSTANTE_FIJO: las marcas del servicio
    # derivan de él (T-3), no del reloj de pared.
    assert web.reloj_utc() == INSTANTE_FIJO
