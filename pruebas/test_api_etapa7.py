"""API de la Etapa 7: cadena documental NAVIERA/AGENTE/AUTORIDAD (§14.7-§14.9).

Verifica el flujo: NAVIERA crea manifiesto → AGENTE presenta declaración y
solicita levante → AUTORIDAD otorga con canal. Cada rol no facultado recibe 403.
"""

import pytest

from pruebas.utilidades_logica import PublicadorCapturado
from pruebas.utilidades_web import crear_usuario, crear_web, entrar
from web.aplicacion import crear_aplicacion
from web.contexto import CLAVE_CONTEXTO
from web.modelos.usuario import Rol


@pytest.fixture()
def logica_web(tmp_path):  # type: ignore[no-untyped-def]
    env = crear_web(tmp_path)
    configuracion = env.app.extensions[CLAVE_CONTEXTO].configuracion
    publicador = PublicadorCapturado()
    env.app = crear_aplicacion(
        configuracion,
        env.bd,
        reloj_epoch=env.reloj_epoch,
        fabrica_instante=env.reloj_utc,
        publicador_logica=publicador,
    )
    for nombre, rol in (
        ("terminal", Rol.TERMINAL),
        ("naviera", Rol.NAVIERA),
        ("agente", Rol.AGENTE),
        ("autoridad", Rol.AUTORIDAD),
        ("transportista", Rol.TRANSPORTISTA),
    ):
        crear_usuario(env, nombre, rol, "clave-" + nombre)
    return env


def _id_transportista(env) -> int:  # type: ignore[no-untyped-def]
    """Id real del transportista: el manifiesto exige uno registrado y activo (§9.3)."""
    return env.usuarios.con_hash_por_username("transportista")[0].id


def _sembrar_catalogo(env):  # type: ignore[no-untyped-def]
    """Siembra contenedor y transportista para que el manifiesto pase las FK."""
    transportista_id = _id_transportista(env)  # fuera del candado: no es reentrante
    with env.bd.candado:
        env.bd.conexion.execute(
            "INSERT OR IGNORE INTO contenedor (id, descripcion) VALUES ('C10','test')"
        )
        env.bd.conexion.execute(
            "INSERT OR IGNORE INTO vehiculo (identificador, transportista_id, tara_g) "
            "VALUES ('V10', ?, 950)",
            (transportista_id,),
        )
        env.bd.conexion.commit()


def test_cadena_documental_completa(logica_web) -> None:  # type: ignore[no-untyped-def]
    env = logica_web
    _sembrar_catalogo(env)
    c = env.app.test_client()

    # 1. NAVIERA crea manifiesto.
    entrar(c, "naviera", "clave-naviera")
    r = c.post(
        "/api/manifiestos",
        json={
            "contenedor_id": "C10",
            "tipo_op": "DEPOSITO",
            "peso_declarado_g": 38500,
            "tolerancia_pct": 5,
            "transportista_id": _id_transportista(env),
            "observaciones": "test",
        },
    )
    assert r.status_code == 200
    mid = r.get_json()["manifiesto_id"]

    # 2. AGENTE presenta declaración y solicita levante.
    entrar(c, "agente", "clave-agente")
    r = c.post(
        "/api/declaraciones/presentar",
        json={
            "manifiesto_id": mid,
            "numero": "DEC-001",
            "regimen": "IMPORTACION_DEFINITIVA",
            "descripcion": "Contenedor de prueba",
            "valor": 50000,
        },
    )
    assert r.status_code == 200
    r = c.post(f"/api/manifiestos/{mid}/solicitar-levante", json={})
    assert r.status_code == 200
    lid = r.get_json()["levante_id"]

    # 3. AUTORIDAD otorga levante con canal verde.
    entrar(c, "autoridad", "clave-autoridad")
    r = c.post(f"/api/levantes/{lid}/otorgar", json={"canal": "verde"})
    assert r.status_code == 200
    assert r.get_json()["canal"] == "verde"

    # 4. NAVIERA no puede crear manifiesto para el mismo contenedor (2 pendientes).
    entrar(c, "naviera", "clave-naviera")
    r = c.post(
        "/api/manifiestos",
        json={
            "contenedor_id": "C10",
            "tipo_op": "DEPOSITO",
            "peso_declarado_g": 1000,
            "tolerancia_pct": 5,
            "transportista_id": _id_transportista(env),
            "observaciones": "",
        },
    )
    assert r.status_code == 409  # CONTENEDOR_CON_PENDIENTE


def test_roles_no_facultados_reciben_403(logica_web) -> None:  # type: ignore[no-untyped-def]
    env = logica_web
    c = env.app.test_client()
    # NAVIERA no puede presentar declaraciones.
    entrar(c, "naviera", "clave-naviera")
    assert c.post("/api/declaraciones/presentar", json={}).status_code == 403
    # AGENTE no puede crear manifiestos.
    entrar(c, "agente", "clave-agente")
    assert c.post("/api/manifiestos", json={}).status_code == 403
    # AUTORIDAD no puede crear manifiestos.
    entrar(c, "autoridad", "clave-autoridad")
    assert c.post("/api/manifiestos", json={}).status_code == 403


def test_autoridad_retiene_levante_con_motivo(logica_web) -> None:  # type: ignore[no-untyped-def]
    env = logica_web
    _sembrar_catalogo(env)
    c = env.app.test_client()
    entrar(c, "naviera", "clave-naviera")
    mid = c.post(
        "/api/manifiestos",
        json={
            "contenedor_id": "C10",
            "tipo_op": "DEPOSITO",
            "peso_declarado_g": 1000,
            "tolerancia_pct": 5,
            "transportista_id": _id_transportista(env),
            "observaciones": "",
        },
    ).get_json()["manifiesto_id"]
    entrar(c, "agente", "clave-agente")
    c.post(
        "/api/declaraciones/presentar",
        json={
            "manifiesto_id": mid,
            "numero": "DEC-002",
            "regimen": "DEPOSITO_TEMPORAL",
            "descripcion": "Contenedor de prueba",
            "valor": 1000,
        },
    )
    lid = c.post(f"/api/manifiestos/{mid}/solicitar-levante", json={}).get_json()["levante_id"]
    entrar(c, "autoridad", "clave-autoridad")
    assert (
        c.post(f"/api/levantes/{lid}/retener", json={"motivo": "documento vencido"}).status_code
        == 200
    )
    assert (
        c.post(f"/api/levantes/{lid}/retener", json={"motivo": "x"}).status_code == 409
    )  # ya resuelto
