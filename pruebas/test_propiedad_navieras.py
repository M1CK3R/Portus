"""Prueba P11: aislamiento entre navieras — el filtro de propiedad va en SQL (§7.4, §7.5.2).

Una NAVIERA consulta el listado y solo recibe sus manifiestos; la otra
naviera no aparece. TRANSPORTISTA ni siquiera accede a la web (§7.1).
"""

import pytest

from pruebas.utilidades_web import crear_usuario, crear_web, entrar
from web.modelos.usuario import Rol
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos

CONTRASENA = "clave-isolamiento-123"
CONTRASENA_TRANSPORTISTA = "clave-transportista-123"


@pytest.fixture()
def web(tmp_path):
    web_prueba = crear_web(tmp_path)
    crear_usuario(web_prueba, "terminal01", Rol.TERMINAL, CONTRASENA)
    crear_usuario(web_prueba, "naviera01", Rol.NAVIERA, CONTRASENA)
    crear_usuario(web_prueba, "naviera02", Rol.NAVIERA, CONTRASENA)
    crear_usuario(web_prueba, "agente01", Rol.AGENTE, CONTRASENA)
    crear_usuario(web_prueba, "transportista01", Rol.TRANSPORTISTA, CONTRASENA_TRANSPORTISTA)
    # Catálogo mínimo para las claves foráneas del manifiesto (BD-3). C-A se
    # usa para la demo del aislamiento; §17.3 impide dos pendientes del mismo
    # contenedor, así que la naviera B declara C-C, no C-A.
    with web_prueba.bd.candado:
        web_prueba.bd.conexion.executemany(
            "INSERT OR IGNORE INTO contenedor (id, descripcion) VALUES (?, ?)",
            (
                ("C-A", "Contenedor de la naviera A"),
                ("C-B", "Contenedor de la naviera A"),
                ("C-C", "Contenedor de la naviera B"),
            ),
        )
        web_prueba.bd.conexion.commit()
    manifiestos = RepositorioManifiestos(web_prueba.bd)
    id_naviera_a = web_prueba.usuarios.con_hash_por_username("naviera01")[0].id
    id_naviera_b = web_prueba.usuarios.con_hash_por_username("naviera02")[0].id
    id_transportista = web_prueba.usuarios.con_hash_por_username("transportista01")[0].id
    manifiestos.crear_demo(
        "C-A", id_naviera_a, id_transportista, "DEPOSITO", 20000, "2026-09-20T14:00:00.000Z"
    )
    manifiestos.crear_demo(
        "C-B", id_naviera_a, id_transportista, "RETIRO", 18000, "2026-09-20T14:05:00.000Z"
    )
    manifiestos.crear_demo(
        "C-C", id_naviera_b, id_transportista, "DEPOSITO", 21000, "2026-09-20T14:10:00.000Z"
    )
    yield web_prueba
    web_prueba.bd.cerrar()


def _cliente_como(web, username: str, contrasena: str):
    cliente = web.app.test_client()
    entrar(cliente, username, contrasena)
    return cliente


def test_naviera_a_solo_ve_sus_manifiestos_y_no_los_de_la_naviera_b(web):
    cliente = _cliente_como(web, "naviera01", CONTRASENA)
    cuerpo = cliente.get("/api/manifiestos").get_json()
    assert len(cuerpo["manifiestos"]) == 2
    assert all(fila["contenedor_id"] in ("C-A", "C-B") for fila in cuerpo["manifiestos"])


def test_naviera_b_solo_ve_el_suyo_y_los_de_a_no_aparecen(web):
    cliente = _cliente_como(web, "naviera02", CONTRASENA)
    cuerpo = cliente.get("/api/manifiestos").get_json()
    assert len(cuerpo["manifiestos"]) == 1
    assert cuerpo["manifiestos"][0]["contenedor_id"] == "C-C"


def test_terminal_agente_y_autoridad_ven_el_listado_completo(web):
    for username in ("terminal01", "agente01"):
        cliente = _cliente_como(web, username, CONTRASENA)
        cuerpo = cliente.get("/api/manifiestos").get_json()
        assert len(cuerpo["manifiestos"]) == 3, username


def test_el_repositorio_filtra_en_la_consulta_y_no_en_memoria(web):
    # §7.5.2: el WHERE naviera_id = ? pertenece al repositorio (único lugar con
    # SQL, A-2); a nivel de repositorio el filtro también aísla por id.
    repositorio = RepositorioManifiestos(web.bd)
    id_naviera_a = web.usuarios.con_hash_por_username("naviera01")[0].id
    id_naviera_b = web.usuarios.con_hash_por_username("naviera02")[0].id
    assert {fila.naviera_id for fila in repositorio.listar(naviera_id=id_naviera_a)} == {
        id_naviera_a
    }
    assert {fila.naviera_id for fila in repositorio.listar(naviera_id=id_naviera_b)} == {
        id_naviera_b
    }
    assert len(repositorio.listar()) == 3  # sin filtro: listado completo (TERMINAL)


def test_transportista_no_accede_ni_a_la_web_ni_a_la_api(web):
    cliente = web.app.test_client()
    respuesta = cliente.post(
        "/api/login",
        json={"username": "transportista01", "password": CONTRASENA_TRANSPORTISTA},
    )
    assert respuesta.status_code == 403  # §7.1: sin interfaz web; P11 sin excepción
    assert cliente.get("/api/manifiestos").status_code == 401  # nunca tuvo sesión
