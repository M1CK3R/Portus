"""API de la Etapa 6 (SPECS §14): sinóptico, patio, grúa, alarmas, citas,
vinculación, comandos y reportes. La matriz §7.4 se aplica en el servidor y
los roles no facultados reciben 403 explícito."""

import pytest

from pruebas.utilidades_logica import (
    PublicadorCapturado,
    enviar,
    sembrar_operacion,
)
from pruebas.utilidades_web import crear_usuario, crear_web, entrar
from web.aplicacion import crear_aplicacion
from web.contexto import CLAVE_CONTEXTO
from web.modelos.usuario import Rol
from web.repositorios.repositorio_levantes import RepositorioLevantes
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_plazas import RepositorioPlazas


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
    ):
        crear_usuario(env, nombre, rol, "clave-" + nombre)
    nucleo = env.app.extensions[CLAVE_CONTEXTO].nucleo
    from pruebas.utilidades_logica import LogicaPrueba

    logica = LogicaPrueba(
        nucleo=nucleo,
        bd=env.bd,
        reloj=env.reloj_utc,
        publicador=publicador,
        plazas=RepositorioPlazas(env.bd),
        manifiestos=RepositorioManifiestos(env.bd),
        levantes=RepositorioLevantes(env.bd),
    )
    return env, logica


def _entrar_terminal(env):  # type: ignore[no-untyped-def]
    cliente = env.app.test_client()
    entrar(cliente, "terminal", "clave-terminal")
    return cliente


def test_operacion_snapshot_solo_terminal(logica_web) -> None:  # type: ignore[no-untyped-def]
    env, logica = logica_web
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    cliente = _entrar_terminal(env)
    respuesta = cliente.get("/api/operacion")
    assert respuesta.status_code == 200
    datos = respuesta.get_json()
    assert "plazas" in datos and "posiciones" in datos and "celdas" in datos
    cliente.get("/api/logout")
    entrar(cliente, "naviera", "clave-naviera")
    assert cliente.get("/api/operacion").status_code == 403  # §7.4: sinóptico es TERMINAL


def test_patio_inventario_y_bloqueo(logica_web) -> None:  # type: ignore[no-untyped-def]
    env, logica = logica_web
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    enviar(logica, "transferencia.evento", {"evento": "ALINEADO", "veh": "V01"}, seq=2)
    enviar(
        logica,
        "patio.cambio",
        {"posicion": "P1", "nivel": 1, "contenedor": "C01", "estado": "OCUPADA"},
        seq=3,
    )
    cliente = _entrar_terminal(env)
    datos = cliente.get("/api/patio").get_json()
    assert any(c["contenedor_id"] == "C01" for c in datos["celdas"])
    assert any(i["contenedor_id"] == "C01" for i in datos["inventario"])
    # Bloquear una posición libre y luego liberarla.
    # 202: PosicionBloquear viaja al controlador; la BD cambia solo con su ACK.
    assert cliente.post("/api/patio/posiciones/P2/bloquear").status_code == 202
    assert cliente.post("/api/patio/posiciones/P2/liberar").status_code == 409  # no bloqueada
    assert cliente.post("/api/patio/posiciones/P9/bloquear").status_code == 404


def test_grua_estado_y_exportar_csv(logica_web) -> None:  # type: ignore[no-untyped-def]
    env, logica = logica_web
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    # PES de entrada dentro de tolerancia: EnGarita → EnRuta (§8.1).
    enviar(
        logica,
        "pesaje.medicion",
        {"veh": "V01", "peso_g": 38_600, "muestras": 10, "meseta": True},
        seq=2,
    )
    enviar(logica, "transferencia.evento", {"evento": "ALINEADO", "veh": "V01"}, seq=3)
    enviar(logica, "grua.paso", {"paso": "FIN", "resultado": "OK", "contenedor": "C01"}, seq=4)
    cliente = _entrar_terminal(env)
    datos = cliente.get("/api/grua").get_json()
    assert datos["cantidad_pendiente"] == 0  # plan completado
    # Exportación CSV del rango que cubre el ciclo registrado.
    csv_resp = cliente.get(
        "/api/grua/exportar?inicio=2026-09-20T00:00:00.000Z&fin=2026-09-21T00:00:00.000Z"
    )
    assert csv_resp.status_code == 200
    assert "tipo" in csv_resp.text  # cabecera del CSV
    assert cliente.get("/api/grua/exportar").status_code == 422  # rango requerido


def test_alarmas_reconocer_y_silenciar(logica_web) -> None:  # type: ignore[no-untyped-def]
    env, logica = logica_web
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    enviar(
        logica,
        "pesaje.medicion",
        {"veh": "V01", "peso_g": 45_000, "muestras": 10, "meseta": True},
        seq=2,
    )  # RT01 + AL09 (media)
    cliente = _entrar_terminal(env)
    datos = cliente.get("/api/alarmas").get_json()
    assert any(a["codigo"] == "AL09" for a in datos["activas"])
    alarma_id = datos["activas"][0]["id"]
    assert (
        cliente.post(
            f"/api/alarmas/{alarma_id}/reconocer", json={"comentario": "visto"}
        ).status_code
        == 200
    )
    assert cliente.post(f"/api/alarmas/{alarma_id}/reconocer").status_code == 409  # ya reconocida
    # Silenciar emite el comando AlarmaSilenciar (§6.3).
    resp = cliente.post("/api/comandos/AlarmaSilenciar", json={"parametros": {}})
    assert resp.status_code == 200
    assert resp.get_json()["nombre"] == "AlarmaSilenciar"


def test_alarmas_reconocer_todas_baja_media(logica_web) -> None:  # type: ignore[no-untyped-def]
    env, logica = logica_web
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    enviar(
        logica,
        "pesaje.medicion",
        {"veh": "V01", "peso_g": 45_000, "muestras": 10, "meseta": True},
        seq=2,
    )  # AL09 media
    cliente = _entrar_terminal(env)
    resp = cliente.post("/api/alarmas/reconocer-todas")
    assert resp.status_code == 200
    assert resp.get_json()["reconocidas"] >= 1
    assert cliente.get("/api/alarmas").get_json()["activas"] == []  # §13.3


def test_citas_agenda_cancelar_y_bloqueo(logica_web) -> None:  # type: ignore[no-untyped-def]
    env, logica = logica_web
    sembrar_operacion(logica)  # siembra cita en 2026-09-20 08:00
    cliente = _entrar_terminal(env)
    datos = cliente.get("/api/citas?fecha=2026-09-20").get_json()
    assert len(datos["franjas"]) >= 1
    cita_id = datos["franjas"][0]["citas"][0]["id"]
    # Bloquear la franja de la cita.
    inicio = datos["franjas"][0]["inicio"]
    assert cliente.post(f"/api/franjas/2026-09-20/{inicio}/bloquear").status_code == 200
    # Cancelar la cita programada.
    assert cliente.post(f"/api/citas/{cita_id}/cancelar").status_code == 200
    assert cliente.post(f"/api/citas/{cita_id}/cancelar").status_code == 409  # ya cancelada
    assert cliente.get("/api/citas").status_code == 422  # fecha requerida


def test_transportistas_panel_vinculacion(logica_web) -> None:  # type: ignore[no-untyped-def]
    env, logica = logica_web
    sembrar_operacion(logica)  # siembra un transportista (tr-v01)
    cliente = _entrar_terminal(env)
    datos = cliente.get("/api/transportistas").get_json()
    assert len(datos["transportistas"]) >= 1
    assert datos["transportistas"][0]["vinculado"] is False  # sin consumir aún
    # Generar código para el primer transportista.
    tid = datos["transportistas"][0]["id"]
    resp = cliente.post(f"/api/transportistas/{tid}/codigo-vinculacion")
    assert resp.status_code == 200
    assert len(resp.get_json()["codigo"]) == 6  # §15.1


def test_reportes_genera_y_exporta(logica_web) -> None:  # type: ignore[no-untyped-def]
    env, logica = logica_web
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    cliente = _entrar_terminal(env)
    resp = cliente.post(
        "/api/reportes",
        json={
            "etiqueta": "corrida de prueba",
            "inicio": "2026-09-19T00:00:00.000Z",
            "fin": "2026-09-21T00:00:00.000Z",
        },
    )
    assert resp.status_code == 200
    reporte = resp.get_json()["reporte"]
    assert reporte["politica"] == "FASE1"  # §12.4, §16.3
    assert "distancia_total_recorrida" in reporte["resultado"]
    rid = reporte["id"]
    csv_resp = cliente.get(f"/api/reportes/{rid}/exportar")
    assert csv_resp.status_code == 200
    assert "vehiculo" in csv_resp.text  # cabecera del detalle
    assert cliente.get("/api/reportes/999/exportar").status_code == 404


def test_comandos_emitir_solo_terminal(logica_web) -> None:  # type: ignore[no-untyped-def]
    env, _ = logica_web
    cliente = _entrar_terminal(env)
    resp = cliente.post("/api/comandos/AbrirTalanquera", json={"parametros": {}})
    assert resp.status_code == 200
    assert "cmd_id" in resp.get_json()
    cliente.get("/api/logout")
    entrar(cliente, "naviera", "clave-naviera")
    assert cliente.post("/api/comandos/AbrirTalanquera", json={}).status_code == 403


def test_retenciones_filtran_por_causa(logica_web) -> None:  # type: ignore[no-untyped-def]
    env, logica = logica_web
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    enviar(
        logica,
        "pesaje.medicion",
        {"veh": "V01", "peso_g": 45_000, "muestras": 10, "meseta": True},
        seq=2,
    )  # RT01
    cliente = _entrar_terminal(env)
    todas = cliente.get("/api/retenciones").get_json()["retenciones"]
    assert any(r["causa"] == "RT01" for r in todas)
    filtradas = cliente.get("/api/retenciones?causa=RT03").get_json()["retenciones"]
    assert filtradas == []  # no hay RT03
