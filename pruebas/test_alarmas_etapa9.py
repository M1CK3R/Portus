"""Etapa 9 · Alarmas AL01-AL14 (SPECS §13): catálogo, ingreso, ciclo de vida y dedup.

Una alarma no desaparece sola; solo TERMINAL la reconoce, CRITICA y ALTA una
por una (§13.3); AL01 sigue activa aunque el enlace vuelva (§13.4); la misma
alarma activa acumula repeticiones (§13.4 [DEC], docs/alarmas.md).
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from pruebas.utilidades_logica import (
    LogicaPrueba,
    PublicadorCapturado,
    crear_logica,
    enviar,
)
from pruebas.utilidades_web import crear_usuario, crear_web, entrar
from web.aplicacion import crear_aplicacion
from web.contexto import CLAVE_CONTEXTO
from web.modelos.alarma import DEFINICIONES, CodigoAlarma
from web.modelos.usuario import Rol
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.servicios.servicio_alarmas import ErrorAlarma

MS_POR_MINUTO = 60_000


@pytest.fixture()
def logica(tmp_path):  # type: ignore[no-untyped-def]
    logica_prueba = crear_logica(tmp_path)
    yield logica_prueba
    logica_prueba.bd.cerrar()


def _activas(logica: LogicaPrueba, codigo: str) -> list:  # type: ignore[type-arg]
    return [a for a in logica.nucleo.alarmas_svc.activas() if a.codigo == codigo]


def _al01_del_puente(logica: LogicaPrueba, id_evento: str) -> None:
    datos = {"codigo": "AL01", "severidad": "CRITICA", "ms_sin_latido": 15_200}
    enviar(logica, "alarma.servidor", datos, seq=0, id_evento=id_evento)


def test_el_catalogo_tiene_las_14_con_severidad_y_origen_de_13_1() -> None:
    severidades = {codigo.value: d.severidad.value for codigo, d in DEFINICIONES.items()}

    assert len(DEFINICIONES) == 14
    assert [c for c, s in severidades.items() if s == "CRITICA"] == ["AL01", "AL02", "AL03", "AL04"]
    assert DEFINICIONES[CodigoAlarma.AL13].severidad.value == "BAJA"
    assert DEFINICIONES[CodigoAlarma.AL02].origen == "controlador"


def test_alm_del_controlador_se_guarda_con_la_severidad_del_catalogo(logica) -> None:  # type: ignore[no-untyped-def]
    enviar(logica, "alarma.controlador", {"codigo": "AL03", "severidad": "BAJA"}, seq=5)

    (al03,) = _activas(logica, "AL03")

    assert (al03.severidad, al03.origen) == ("CRITICA", "controlador")
    assert al03.descripcion == "Pérdida de referencia de posición de la grúa"
    assert logica.publicador.datos_de("alarma.resumen")[-1] == {"activas": 1}


def test_alm_con_codigo_desconocido_se_descarta(logica) -> None:  # type: ignore[no-untyped-def]
    enviar(logica, "alarma.controlador", {"codigo": "AL99", "severidad": "ALTA"}, seq=5)

    assert logica.nucleo.alarmas_svc.activas() == []


def test_al01_del_puente_sigue_activa_aunque_el_enlace_vuelva(logica) -> None:  # type: ignore[no-untyped-def]
    _al01_del_puente(logica, "al01-a")
    enviar(logica, "enlace.estado", {"enlace": "activo", "puente": "activo"}, seq=0)

    (al01,) = _activas(logica, "AL01")

    assert (al01.severidad, al01.estado) == ("CRITICA", "activa")


def test_las_alarmas_propias_de_la_web_no_se_registran_dos_veces(logica) -> None:  # type: ignore[no-untyped-def]
    """La web recibe de vuelta su alarma.servidor (p. ej. AL09): no la duplica."""
    enviar(logica, "alarma.servidor", {"codigo": "AL09", "diferencia_pct": 14.4}, seq=0)

    assert logica.nucleo.alarmas_svc.activas() == []


def test_la_misma_alarma_activa_suma_repeticiones(logica) -> None:  # type: ignore[no-untyped-def]
    enviar(logica, "alarma.controlador", {"codigo": "AL06"}, seq=1)
    enviar(logica, "alarma.controlador", {"codigo": "AL06"}, seq=2)

    (al06,) = _activas(logica, "AL06")

    assert al06.repeticiones == 2


def test_tras_reconocerla_una_nueva_ocurrencia_abre_otra_fila(logica) -> None:  # type: ignore[no-untyped-def]
    enviar(logica, "alarma.controlador", {"codigo": "AL06"}, seq=1)
    terminal = _terminal(logica)
    (primera,) = _activas(logica, "AL06")
    logica.nucleo.alarmas_svc.reconocer(primera.id, terminal, "terminal01", "revisada")

    enviar(logica, "alarma.controlador", {"codigo": "AL06"}, seq=2)

    (segunda,) = _activas(logica, "AL06")
    historica = logica.nucleo.alarmas_svc.historicas()[0]
    assert segunda.id != primera.id and segunda.repeticiones == 1
    assert (historica.comentario, historica.reconocida_por_usuario) == ("revisada", "terminal01")


def test_reconocer_dos_veces_se_rechaza(logica) -> None:  # type: ignore[no-untyped-def]
    enviar(logica, "alarma.controlador", {"codigo": "AL05"}, seq=1)
    (al05,) = _activas(logica, "AL05")
    terminal = _terminal(logica)
    logica.nucleo.alarmas_svc.reconocer(al05.id, terminal, "terminal01")

    with pytest.raises(ErrorAlarma):
        logica.nucleo.alarmas_svc.reconocer(al05.id, terminal, "terminal01")


def test_reconocer_todas_deja_criticas_y_altas(logica) -> None:  # type: ignore[no-untyped-def]
    for seq, codigo in enumerate(("AL02", "AL05", "AL09", "AL14"), start=1):
        enviar(logica, "alarma.controlador", {"codigo": codigo}, seq=seq)

    cantidad = logica.nucleo.alarmas_svc.reconocer_todas_baja_media(_terminal(logica), "t")

    restantes = sorted(a.codigo for a in logica.nucleo.alarmas_svc.activas())
    assert cantidad == 2 and restantes == ["AL02", "AL05"]


def test_la_reconciliacion_aplica_las_alarmas_que_guardo_el_puente(logica) -> None:  # type: ignore[no-untyped-def]
    """E14: la web arrancó después que el puente y se perdió AL01 retroactiva y un ALM."""
    filas = [
        ("al01-retro", "alarma.servidor", {"codigo": "AL01", "retroactiva": True}, "srv/alarma"),
        ("alm-7", "alarma.controlador", {"codigo": "AL02", "severidad": "CRITICA"}, "evt/alarma"),
    ]
    with logica.bd.candado:
        for id_evento, tipo, datos, topico in filas:
            logica.bd.conexion.execute(
                "INSERT INTO evento (id, ts, origen, tipo, seq, datos, topico) "
                "VALUES (?, '2026-09-20T13:59:00.000Z', 'servidor', ?, NULL, ?, ?)",
                (id_evento, tipo, json.dumps(datos), f"portus/{topico}"),
            )
        logica.bd.conexion.commit()

    primera = logica.nucleo.reconciliar_alarmas("2026-09-20T00:00:00.000Z")
    segunda = logica.nucleo.reconciliar_alarmas("2026-09-20T00:00:00.000Z")

    assert (primera, segunda) == (2, 0)
    assert sorted(a.codigo for a in logica.nucleo.alarmas_svc.activas()) == ["AL01", "AL02"]


def test_al13_a_las_dos_horas_una_vez_por_estadia(logica) -> None:  # type: ignore[no-untyped-def]
    with logica.bd.candado:
        logica.bd.conexion.execute("INSERT INTO contenedor (id, descripcion) VALUES ('C07', 'x')")
        logica.bd.conexion.commit()
    # El PAT entra con la marca del reloj falso (14:03 UTC): esa es su hora de ingreso.
    enviar(
        logica,
        "patio.cambio",
        {"posicion": "P2", "nivel": 1, "contenedor": "C07", "estado": "OCUPADA"},
        seq=1,
    )
    vigilante = logica.nucleo.vigilante_permanencia

    logica.reloj.avanzar_ms(119 * MS_POR_MINUTO)
    antes = vigilante.revisar()
    logica.reloj.avanzar_ms(2 * MS_POR_MINUTO)
    primera = vigilante.revisar()
    segunda = vigilante.revisar()

    assert (antes, primera, segunda) == ([], ["C07"], [])
    (al13,) = _activas(logica, "AL13")
    assert al13.datos["contenedor"] == "C07" and al13.severidad == "BAJA"


def _terminal(logica: LogicaPrueba) -> int:
    usuarios = RepositorioUsuarios(logica.bd)
    if usuarios.con_hash_por_username("terminal01") is None:
        usuarios.crear("terminal01", "x", Rol.TERMINAL, "Terminal", "2026-09-20T13:00:00.000Z")
    return usuarios.con_hash_por_username("terminal01")[0].id


# ----------------------------------------------------------------------- API


@pytest.fixture()
def web(tmp_path):  # type: ignore[no-untyped-def]
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
    nucleo = env.app.extensions[CLAVE_CONTEXTO].nucleo
    nucleo.alarmas_svc.procesar_alarma_controlador({"codigo": "AL02"}, "2026-09-20T14:00:00Z")
    yield env, publicador
    env.bd.cerrar()


def _cliente(env, rol: str):  # type: ignore[no-untyped-def]
    cliente = env.app.test_client()
    entrar(cliente, rol, "clave-" + rol)
    return cliente


def test_solo_terminal_ve_y_reconoce_alarmas(web) -> None:  # type: ignore[no-untyped-def]
    web, _ = web
    autoridad = _cliente(web, "autoridad")
    alarma_id = _cliente(web, "terminal").get("/api/alarmas").get_json()["activas"][0]["id"]

    listado = autoridad.get("/api/alarmas")
    reconocer = autoridad.post(f"/api/alarmas/{alarma_id}/reconocer", json={})

    assert (listado.status_code, reconocer.status_code) == (403, 403)


def test_la_api_reconoce_con_comentario_y_expone_el_catalogo(web) -> None:  # type: ignore[no-untyped-def]
    web, _ = web
    terminal = _cliente(web, "terminal")
    datos = terminal.get("/api/alarmas").get_json()
    alarma_id = datos["activas"][0]["id"]

    respuesta = terminal.post(f"/api/alarmas/{alarma_id}/reconocer", json={"comentario": "rearme"})
    otra_vez = terminal.post(f"/api/alarmas/{alarma_id}/reconocer", json={})

    reconocida = respuesta.get_json()["alarma"]
    assert (reconocida["comentario"], reconocida["reconocida_por_usuario"]) == (
        "rearme",
        "terminal",
    )
    assert otra_vez.status_code == 409
    assert len(datos["catalogo"]) == 14
    assert terminal.get("/api/alarmas?severidad=GRAVE").status_code == 422


def test_comando_no_disponible_responde_409(web) -> None:  # type: ignore[no-untyped-def]
    web, _ = web
    nucleo = web.app.extensions[CLAVE_CONTEXTO].nucleo
    nucleo.comandos_svc.actualizar_estado("NORMAL", "REPOSO", "2026-09-20T14:00:00Z")

    respuesta = _cliente(web, "terminal").post("/api/comandos/GruaReanudar", json={})

    assert respuesta.status_code == 409
    assert respuesta.get_json()["error"] == "COMANDO_NO_DISPONIBLE"


def test_reconocer_publica_el_nuevo_recuento(web) -> None:  # type: ignore[no-untyped-def]
    web, publicador = web
    nucleo = web.app.extensions[CLAVE_CONTEXTO].nucleo
    alarma_id = nucleo.alarmas_svc.activas()[0].id

    _cliente(web, "terminal").post(f"/api/alarmas/{alarma_id}/reconocer", json={})

    assert publicador.datos_de("alarma.reconocida")[-1]["alarma"] == alarma_id
    assert publicador.datos_de("alarma.resumen")[-1] == {"activas": 0}


def test_ventana_de_reconciliacion_ignora_lo_anterior(logica) -> None:  # type: ignore[no-untyped-def]
    with logica.bd.candado:
        logica.bd.conexion.execute(
            "INSERT INTO evento (id, ts, origen, tipo, seq, datos, topico) VALUES "
            "('viejo', '2026-09-18T10:00:00.000Z', 'servidor', 'alarma.servidor', NULL, "
            "'{\"codigo\": \"AL01\"}', 'portus/srv/alarma')"
        )
        logica.bd.conexion.commit()
    desde = (datetime(2026, 9, 20, tzinfo=UTC) - timedelta(hours=24)).isoformat()

    assert logica.nucleo.reconciliar_alarmas(desde.replace("+00:00", "Z")) == 0
