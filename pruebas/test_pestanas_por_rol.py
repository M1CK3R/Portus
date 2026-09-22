"""Pruebas de pestañas por rol: §7.6 — cantidad y nombres exactos, solo los del rol."""

import pytest

from pruebas.utilidades_web import crear_usuario, crear_web, entrar
from web.modelos.pestanas import PESTANAS_POR_ROL
from web.modelos.usuario import Rol

CONTRASENA = "clave-pestanas-123"

USUARIOS_POR_ROL = {
    Rol.TERMINAL: "terminal01",
    Rol.NAVIERA: "naviera01",
    Rol.AGENTE: "agente01",
    Rol.AUTORIDAD: "autoridad01",
}


@pytest.fixture()
def web(tmp_path):
    web_prueba = crear_web(tmp_path)
    for rol, username in USUARIOS_POR_ROL.items():
        crear_usuario(web_prueba, username, rol, CONTRASENA)
    yield web_prueba
    web_prueba.bd.cerrar()


@pytest.mark.parametrize("rol", list(USUARIOS_POR_ROL))
def test_cada_rol_ve_sus_pestanas_con_los_nombres_exactos_del_specs(web, rol):
    cliente = web.app.test_client()
    entrar(cliente, USUARIOS_POR_ROL[rol], CONTRASENA)
    for pestana in PESTANAS_POR_ROL[rol]:
        respuesta = cliente.get(f"/pestanas/{pestana.slug}")
        assert respuesta.status_code == 200, pestana
        assert pestana.titulo.encode() in respuesta.data
        # §7.3.3: usuario y rol visibles de forma permanente en la interfaz.
        assert rol.value.encode() in respuesta.data


def test_terminal_ve_las_ocho_pestanas_y_navega_por_su_primera(web):
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    inicio = cliente.get("/")
    assert inicio.status_code == 302
    assert inicio.headers["Location"].endswith("/pestanas/operacion")
    for titulo in (
        "Operación",
        "Turnos",
        "Retenciones",
        "Patio",
        "Grúa",
        "Alarmas",
        "Citas",
        "Reportes",
    ):
        assert titulo.encode() in cliente.get("/pestanas/operacion").data


def test_naviera_ve_dos_pestanas_y_no_recibe_operacion_de_terminal(web):
    cliente = web.app.test_client()
    entrar(cliente, "naviera01", CONTRASENA)
    respuesta = cliente.get("/pestanas/manifiestos")
    assert respuesta.status_code == 200
    assert b"Manifiestos" in respuesta.data
    assert b"Operaci" not in respuesta.data  # la pestaña de TERMINAL no se renderiza
    assert cliente.get("/pestanas/operacion").status_code == 404  # ni se sirve (§7.6)


def test_autoridad_ve_tres_pestanas_aduaneras(web):
    cliente = web.app.test_client()
    entrar(cliente, "autoridad01", CONTRASENA)
    assert cliente.get("/pestanas/solicitudes_levante").status_code == 200
    assert cliente.get("/pestanas/retenciones_aduaneras").status_code == 200
    assert cliente.get("/pestanas/consulta_carga").status_code == 200


def test_la_cantidad_de_pestanas_por_rol_es_la_del_specs(web):
    assert len(PESTANAS_POR_ROL[Rol.TERMINAL]) == 8
    assert len(PESTANAS_POR_ROL[Rol.NAVIERA]) == 2
    assert len(PESTANAS_POR_ROL[Rol.AGENTE]) == 2
    assert len(PESTANAS_POR_ROL[Rol.AUTORIDAD]) == 3
    assert len(PESTANAS_POR_ROL[Rol.TRANSPORTISTA]) == 0  # sin interfaz web (§7.6)
