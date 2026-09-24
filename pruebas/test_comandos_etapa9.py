"""Etapa 9 · Los 13 comandos remotos (SPECS §6.1-§6.5).

⚠️ §6.2 regla 5: ningún comando se ejecuta cuando se cumple su condición de
rechazo. Se prueba comando por comando sobre los enclavamientos simulados
(referencia del firmware) y, en el servidor, que un NAK genera AL14 con la
causa exacta y que la disponibilidad de §6.3 se aplica también en la API.
"""

import json

import pytest

from herramientas.enclavamientos_simulados import EstadoFisico, evaluar_comando
from herramientas.simulador_controlador import SimuladorControlador
from pruebas.utilidades_logica import crear_logica, enviar
from puente.protocolo import CAUSAS_RECHAZO_COMANDO, NOMBRES_COMANDOS
from web.modelos.comando import TEXTO_CAUSA_RECHAZO
from web.servicios.servicio_comandos import ErrorComando

# (comando, parámetros, sensores que activan la condición, causa exacta de §6.5)
CONDICIONES_DE_RECHAZO = [
    ("AbrirTalanquera", {}, {"vehiculo_bajo_talanquera": True}, "VEH_BAJO_TALANQUERA"),
    ("CerrarTalanquera", {}, {"vehiculo_bajo_talanquera": True}, "VEH_BAJO_TALANQUERA"),
    ("AbrirPuertaSalida", {}, {"vehiculo_bajo_puerta": True}, "VEH_BAJO_PUERTA"),
    ("AgujaRecta", {}, {"vehiculo_sobre_aguja": True}, "VEH_SOBRE_AGUJA"),
    ("AgujaParqueo", {}, {"vehiculo_sobre_aguja": True}, "VEH_SOBRE_AGUJA"),
    (
        "AgujaLiberar",
        {"plaza": "1"},
        {"vehiculo_sobre_aguja": True, "vehiculos_en_parqueo": 1},
        "VEH_SOBRE_AGUJA",
    ),
    ("AgujaLiberar", {"plaza": "1"}, {"vehiculos_en_parqueo": 0}, "PARQUEO_VACIO"),
    ("GruaReferenciar", {}, {"grua_con_carga": True}, "GRUA_CON_CARGA"),
    ("GruaReferenciar", {}, {"posiciones_en_trabajo": {"P3"}}, "GRUA_EN_TRABAJO"),
    ("GruaReanudar", {}, {"grua_en_falla": True, "grua_suspendida": True}, "GRUA_EN_FALLA"),
    ("PosicionBloquear", {"pos": "P3"}, {"posiciones_en_trabajo": {"P3"}}, "POS_EN_TRABAJO"),
    (
        "PosicionLiberar",
        {"pos": "P2"},
        {"inconsistencias": {"P2"}, "posiciones_bloqueadas": {"P2"}},
        "INCONSISTENCIA_PERSISTE",
    ),
    (
        "ModoMantenimiento",
        {"valor": "ACTIVAR"},
        {"posiciones_en_trabajo": {"P1"}},
        "GRUA_EN_TRABAJO",
    ),
    (
        "ModoMantenimiento",
        {"valor": "ACTIVAR"},
        {"vehiculo_en_transferencia": True},
        "VEH_EN_TRANSFERENCIA",
    ),
]

PARAMETROS_VALIDOS = {
    "AgujaLiberar": {"plaza": "1"},
    "PosicionBloquear": {"pos": "P1"},
    "PosicionLiberar": {"pos": "P1"},
    "ModoMantenimiento": {"valor": "ACTIVAR"},
}


def _simulador(**sensores: object) -> SimuladorControlador:
    """Simulador sin abrir el puerto: solo se usan sus enclavamientos."""
    return SimuladorControlador(ruta_puerto="/dev/null", fisico=EstadoFisico(**sensores))  # type: ignore[arg-type]


@pytest.mark.parametrize(("nombre", "parametros", "sensores", "causa"), CONDICIONES_DE_RECHAZO)
def test_con_su_condicion_presente_el_comando_se_rechaza_y_no_actua(
    nombre, parametros, sensores, causa
) -> None:  # type: ignore[no-untyped-def]
    simulador = _simulador(**sensores)
    antes = simulador.estado_fisico()

    respuesta = simulador.responder_comando(1, {"nombre": nombre, **parametros})

    assert respuesta == ("NAK", causa)
    assert simulador.estado_fisico() == antes  # nada se movió


@pytest.mark.parametrize("nombre", sorted(NOMBRES_COMANDOS))
def test_sin_condicion_de_rechazo_los_13_comandos_se_aceptan(nombre) -> None:  # type: ignore[no-untyped-def]
    simulador = _simulador(vehiculos_en_parqueo=1)

    respuesta = simulador.responder_comando(
        1, {"nombre": nombre, **PARAMETROS_VALIDOS.get(nombre, {})}
    )

    assert respuesta == ("ACK", None)


@pytest.mark.parametrize("nombre", ["GruaSuspender", "AlarmaSilenciar"])
def test_suspender_y_silenciar_nunca_se_rechazan(nombre) -> None:  # type: ignore[no-untyped-def]
    todo_bloqueado = EstadoFisico(
        vehiculo_bajo_talanquera=True,
        vehiculo_bajo_puerta=True,
        vehiculo_sobre_aguja=True,
        vehiculo_en_transferencia=True,
        grua_con_carga=True,
        grua_en_falla=True,
        posiciones_en_trabajo={"P1"},
    )

    assert evaluar_comando(nombre, {}, todo_bloqueado) is None


def test_un_reintento_con_la_misma_seq_no_actua_dos_veces() -> None:
    simulador = _simulador()

    primera = simulador.responder_comando(7, {"nombre": "AgujaParqueo"})
    segunda = simulador.responder_comando(7, {"nombre": "AgujaParqueo"})

    assert primera == segunda == ("ACK", None)
    assert simulador.estado_fisico().vehiculos_en_parqueo == 1


def test_suspender_y_reanudar_se_reflejan_en_el_latido() -> None:
    simulador = _simulador()

    simulador.responder_comando(1, {"nombre": "GruaSuspender"})
    suspendida = simulador.campos_latido()["grua"]
    simulador.responder_comando(2, {"nombre": "GruaReanudar"})
    simulador.responder_comando(3, {"nombre": "ModoMantenimiento", "valor": "ACTIVAR"})

    assert suspendida == "SUSPENDIDA"
    assert simulador.campos_latido()["grua"] == "REPOSO"
    assert simulador.campos_latido()["modo"] == "MANTENIMIENTO"


def test_cada_causa_de_rechazo_tiene_su_texto_legible() -> None:
    """§6.2 regla 2: la causa exacta se muestra con el texto de §6.5 (web y JS)."""
    assert set(TEXTO_CAUSA_RECHAZO) == CAUSAS_RECHAZO_COMANDO
    with open("web/interfaz/estatico/js/causas_comando.mjs", encoding="utf-8") as archivo:
        js = archivo.read()
    assert all(f"{codigo}:" in js for codigo in CAUSAS_RECHAZO_COMANDO)


# ---------------------------------------------------------------- servidor


def _respuesta(logica, cmd_id: str, estado: str, causa: str | None, sintetica: bool) -> None:  # type: ignore[no-untyped-def]
    envoltorio = {
        "id": f"rsp-{cmd_id}",
        "ts": "2026-09-20T14:03:25.000Z",
        "origen": "puente" if sintetica else "controlador",
        "tipo": "comando.respuesta",
        "seq": None,
        "datos": {
            "cmd_id": cmd_id,
            "nombre": "AbrirTalanquera",
            "estado": estado,
            "causa": causa,
            "sintetica": sintetica,
        },
    }
    logica.nucleo.atender_mensaje("portus/cmd/respuesta", json.dumps(envoltorio).encode())


@pytest.fixture()
def logica(tmp_path):  # type: ignore[no-untyped-def]
    logica_prueba = crear_logica(tmp_path)
    yield logica_prueba
    logica_prueba.bd.cerrar()


@pytest.mark.parametrize(
    ("causa", "sintetica"), [("VEH_BAJO_TALANQUERA", False), ("SIN_RESPUESTA", True)]
)
def test_todo_nak_genera_al14_con_la_causa_exacta(logica, causa, sintetica) -> None:  # type: ignore[no-untyped-def]
    _respuesta(logica, "c-1", "NAK", causa, sintetica)

    al14 = [a for a in logica.nucleo.alarmas_svc.activas() if a.codigo == "AL14"]

    assert len(al14) == 1
    assert al14[0].datos["causa"] == causa
    assert al14[0].datos["texto_causa"] == TEXTO_CAUSA_RECHAZO[causa]
    assert al14[0].datos["sintetica"] is sintetica


def test_un_ack_no_genera_al14(logica) -> None:  # type: ignore[no-untyped-def]
    _respuesta(logica, "c-2", "ACK", None, False)

    assert logica.nucleo.alarmas_svc.activas() == []


def test_reanudar_y_referenciar_respetan_el_estado_del_latido(logica) -> None:  # type: ignore[no-untyped-def]
    comandos = logica.nucleo.comandos_svc
    enviar(logica, "estado.latido", {"modo": "NORMAL", "grua": "IZANDO"}, seq=1)

    with pytest.raises(ErrorComando) as reanudar:
        comandos.emitir("GruaReanudar", {}, "terminal01")
    with pytest.raises(ErrorComando) as referenciar:
        comandos.emitir("GruaReferenciar", {}, "terminal01")
    enviar(logica, "estado.latido", {"modo": "NORMAL", "grua": "SUSPENDIDA"}, seq=2)
    comandos.emitir("GruaReanudar", {}, "terminal01")
    comandos.emitir("GruaReferenciar", {}, "terminal01")

    assert reanudar.value.codigo == referenciar.value.codigo == "COMANDO_NO_DISPONIBLE"
    assert logica.publicador.nombres_de_comandos() == ["GruaReanudar", "GruaReferenciar"]


def test_sin_latido_decide_el_controlador(logica) -> None:  # type: ignore[no-untyped-def]
    logica.nucleo.comandos_svc.emitir("GruaReanudar", {}, "terminal01")

    assert logica.publicador.nombres_de_comandos() == ["GruaReanudar"]
