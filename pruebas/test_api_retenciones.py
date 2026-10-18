"""API de retenciones (Etapa 8, §14.3, §14.9, A9): la matriz se aplica en el servidor.

Se llama a la API sin la UI: la bandeja expone los campos de §14.3, la
AUTORIDAD ve solo las aduaneras y no puede resolver ni corregir causas
operativas (403 auditado, penalización §23.3), y RT05 se ordena solo desde
la cuenta de AUTORIDAD.
"""

import pytest

from pruebas.utilidades_logica import LogicaPrueba, PublicadorCapturado, enviar, sembrar_operacion
from pruebas.utilidades_web import crear_usuario, crear_web, entrar
from web.aplicacion import crear_aplicacion
from web.contexto import CLAVE_CONTEXTO
from web.modelos.usuario import Rol
from web.repositorios.repositorio_levantes import RepositorioLevantes
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_plazas import RepositorioPlazas

PESO_FUERA_DE_TOLERANCIA_G = 45_000


@pytest.fixture()
def entorno(tmp_path):  # type: ignore[no-untyped-def]
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
    for nombre, rol in (("terminal", Rol.TERMINAL), ("autoridad", Rol.AUTORIDAD)):
        crear_usuario(env, nombre, rol, "clave-" + nombre)
    logica = LogicaPrueba(
        nucleo=env.app.extensions[CLAVE_CONTEXTO].nucleo,
        bd=env.bd,
        reloj=env.reloj_utc,
        publicador=publicador,
        plazas=RepositorioPlazas(env.bd),
        manifiestos=RepositorioManifiestos(env.bd),
        levantes=RepositorioLevantes(env.bd),
    )
    yield env, logica
    env.bd.cerrar()


def _cliente(env, rol: str):  # type: ignore[no-untyped-def]
    cliente = env.app.test_client()
    entrar(cliente, rol, "clave-" + rol)
    return cliente


def _rt01(logica: LogicaPrueba) -> None:
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    enviar(
        logica,
        "pesaje.medicion",
        {"veh": "V01", "peso_g": PESO_FUERA_DE_TOLERANCIA_G, "muestras": 10, "meseta": True},
        seq=2,
    )


def test_bandeja_expone_los_campos_de_14_3(entorno) -> None:  # type: ignore[no-untyped-def]
    env, logica = entorno
    _rt01(logica)

    fila = (
        _cliente(env, "terminal")
        .get("/api/retenciones?estado=abierta")
        .get_json()["retenciones"][0]
    )

    assert (fila["vehiculo"], fila["contenedor_id"], fila["causa"]) == ("V01", "C01", "RT01")
    assert (fila["estacion"], fila["plaza"], fila["rol_facultado"]) == (
        "pesaje_entrada",
        1,
        "TERMINAL",
    )
    assert fila["evidencia"]["diferencia_abs_g"] == 44_050 - 38_500
    assert fila["evidencia"]["diferencia_pct"] == pytest.approx(14.42, abs=0.01)
    assert fila["corregible"] is True and fila["creada_en"]


@pytest.mark.parametrize(("consulta", "codigo"), [("causa=RT09", 422), ("estado=cerrada", 422)])
def test_bandeja_rechaza_filtros_invalidos(entorno, consulta, codigo) -> None:  # type: ignore[no-untyped-def]
    env, _ = entorno

    respuesta = _cliente(env, "terminal").get(f"/api/retenciones?{consulta}")

    assert respuesta.status_code == codigo


def test_autoridad_no_ve_ni_resuelve_causas_operativas(entorno) -> None:  # type: ignore[no-untyped-def]
    env, logica = entorno
    _rt01(logica)
    retencion_id = logica.nucleo.retenciones.listar()[0].id
    autoridad = _cliente(env, "autoridad")

    bandeja = autoridad.get("/api/retenciones").get_json()["retenciones"]
    aclarar = autoridad.post(f"/api/retenciones/{retencion_id}/aclarar", json={})
    corregir = autoridad.post(f"/api/retenciones/{retencion_id}/corregir", json={})

    assert bandeja == []  # solo RT03/RT05 (§14.9)
    assert (aclarar.status_code, corregir.status_code) == (403, 403)
    assert aclarar.get_json()["error"] == "ACCION_NO_PERMITIDA"
    with env.bd.candado:
        auditadas = env.bd.conexion.execute(
            "SELECT COUNT(*) FROM auditoria_rechazo WHERE motivo = 'rol_no_facultado_causa'"
        ).fetchone()[0]
    assert auditadas == 2
    assert logica.nucleo.retenciones.buscar_por_id(retencion_id).estado == "abierta"


def test_rechazar_sin_motivo_422_y_doble_resolucion_409(entorno) -> None:  # type: ignore[no-untyped-def]
    env, logica = entorno
    _rt01(logica)
    retencion_id = logica.nucleo.retenciones.listar()[0].id
    terminal = _cliente(env, "terminal")

    sin_motivo = terminal.post(f"/api/retenciones/{retencion_id}/rechazar", json={"motivo": " "})
    aclarada = terminal.post(f"/api/retenciones/{retencion_id}/aclarar", json={})
    otra_vez = terminal.post(f"/api/retenciones/{retencion_id}/aclarar", json={})

    assert (sin_motivo.status_code, aclarada.status_code, otra_vez.status_code) == (422, 200, 409)
    assert otra_vez.get_json()["error"] == "RETENCION_RESUELTA"


def test_autoridad_ordena_rt05_desde_la_api_y_la_terminal_no(entorno) -> None:  # type: ignore[no-untyped-def]
    env, logica = entorno
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    autoridad = _cliente(env, "autoridad")
    turnos = autoridad.get("/api/autoridad/turnos").get_json()["turnos"]
    turno_id = turnos[0]["id"]

    sin_motivo = autoridad.post(f"/api/autoridad/turnos/{turno_id}/retener", json={})
    por_terminal = _cliente(env, "terminal").post(
        f"/api/autoridad/turnos/{turno_id}/retener", json={"motivo": "x"}
    )
    ordenada = autoridad.post(
        f"/api/autoridad/turnos/{turno_id}/retener", json={"motivo": "documento vencido"}
    )

    assert turnos[0]["retenible"] is True and turnos[0]["contenedor_id"] == "C01"
    assert (sin_motivo.status_code, por_terminal.status_code, ordenada.status_code) == (
        422,
        403,
        201,
    )
    assert ordenada.get_json()["retencion"]["causa"] == "RT05"
    bandeja = autoridad.get("/api/retenciones").get_json()["retenciones"]
    assert [fila["causa"] for fila in bandeja] == ["RT05"]


def test_anular_turno_retenido_por_la_api_da_409(entorno) -> None:  # type: ignore[no-untyped-def]
    env, logica = entorno
    _rt01(logica)
    turno_id = logica.nucleo.retenciones.listar()[0].turno_id

    respuesta = _cliente(env, "terminal").post(
        f"/api/turnos/{turno_id}/anular", json={"motivo": "desiste"}
    )

    assert respuesta.status_code == 409
    assert respuesta.get_json()["error"] == "RETENCION_ABIERTA"
