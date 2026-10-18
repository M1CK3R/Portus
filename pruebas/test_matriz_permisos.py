"""Prueba P10: la matriz de permisos se aplica en el servidor en cada endpoint (§7.4, §7.5).

Se llama a la API directamente con cada rol, sin usar la UI: los permitidos
pasan y cualquier otro recibe 403 con mensaje explícito, y cada rechazo
queda en la auditoría (§7.5.5).
"""

import pytest

from pruebas.utilidades_web import crear_usuario, crear_web, entrar
from web.modelos.usuario import Rol

CONTRASENA = "clave-matriz-123"

ROLES_WEB = [Rol.TERMINAL, Rol.NAVIERA, Rol.AGENTE, Rol.AUTORIDAD]


@pytest.fixture()
def web(tmp_path):
    web_prueba = crear_web(tmp_path)
    usuarios = [
        ("terminal01", Rol.TERMINAL),
        ("naviera01", Rol.NAVIERA),
        ("agente01", Rol.AGENTE),
        ("autoridad01", Rol.AUTORIDAD),
        ("transportista01", Rol.TRANSPORTISTA),
    ]
    for username, rol in usuarios:
        crear_usuario(web_prueba, username, rol, CONTRASENA)
    yield web_prueba
    web_prueba.bd.cerrar()


def _cliente_como(web, rol: Rol):
    cliente = web.app.test_client()
    username = {
        Rol.TERMINAL: "terminal01",
        Rol.NAVIERA: "naviera01",
        Rol.AGENTE: "agente01",
        Rol.AUTORIDAD: "autoridad01",
    }[rol]
    entrar(cliente, username, CONTRASENA)
    return cliente


def _ruta_codigo(web):
    """URL real del endpoint de vinculación con un transportista existente."""
    id_transportista = web.usuarios.con_hash_por_username("transportista01")[0].id
    return f"/api/transportistas/{id_transportista}/codigo-vinculacion"


# (ruta en función de la app, método, roles permitidos por la matriz §7.4)
ENDPOINTS = [
    (_ruta_codigo, "post", {Rol.TERMINAL}),  # §7.4: solo TERMINAL genera códigos
    (
        lambda web: "/api/manifiestos",
        "get",
        {Rol.TERMINAL, Rol.NAVIERA, Rol.AGENTE, Rol.AUTORIDAD},  # §7.4: ver manifiestos
    ),
]


@pytest.mark.parametrize("ruta,metodo,permitidos", ENDPOINTS)
def test_cada_rol_permitido_pasa_y_los_demas_reciben_403_explicito(web, ruta, metodo, permitidos):
    for rol in ROLES_WEB:
        cliente = _cliente_como(web, rol)
        respuesta = cliente.open(ruta(web), method=metodo.upper())
        if rol in permitidos:
            assert respuesta.status_code == 200, (rol, ruta)
        else:
            assert respuesta.status_code == 403, (rol, ruta)
            cuerpo = respuesta.get_json()
            # §7.5.1: error explícito con la forma exigida.
            assert cuerpo["error"] == "ACCION_NO_PERMITIDA"
            assert f"El rol {rol.value} no puede" in cuerpo["mensaje"]


def test_sin_sesion_toda_ruta_responde_401(web):
    cliente = web.app.test_client()
    for ruta, metodo, _ in ENDPOINTS:
        respuesta = cliente.open(ruta(web), method=metodo.upper())
        assert respuesta.status_code == 401, ruta
        assert respuesta.get_json()["error"] == "SESION_REQUERIDA"


def test_cada_rechazo_rol_no_permitido_queda_auditado_con_usuario_y_recurso(web):
    auditoria = web.app.extensions["repositorio_auditoria"]
    antes = auditoria.contar()
    cliente = _cliente_como(web, Rol.NAVIERA)
    respuesta = cliente.post(_ruta_codigo(web))
    assert respuesta.status_code == 403
    rechazos = auditoria.ultimos(auditoria.contar() - antes)
    assert len(rechazos) == 1
    rechazo = rechazos[0]
    assert rechazo.username == "naviera01"
    assert rechazo.rol == "NAVIERA"
    assert rechazo.accion == "generar_codigo_vinculacion"
    assert rechazo.recurso.startswith("/api/transportistas/")
    assert rechazo.motivo == "rol_no_permitido"


def test_logout_y_sesion_estan_abiertos_a_cualquier_rol_web(web):
    for rol in ROLES_WEB:
        cliente = _cliente_como(web, rol)
        assert cliente.get("/api/sesion").status_code == 200, rol
        assert cliente.post("/api/logout").status_code == 200, rol
