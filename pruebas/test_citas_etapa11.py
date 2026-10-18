"""Etapa 11: ciclo de vida de la cita y control de ventana (SPECS §11, A11).

Reloj falso: 2026-09-20 14:03:22 UTC = 08:03 en la terminal. ``sembrar_operacion``
deja al vehículo V01 con cita en la franja indicada (08:00 por omisión, con la
ventana 08:00-08:20 abierta).
"""

from pathlib import Path

import pytest

from herramientas.crear_datos_semilla import crear as crear_datos
from herramientas.crear_operacion_demo import OpcionesDemo
from herramientas.crear_operacion_demo import crear as crear_operacion
from pruebas.utilidades_logica import CREADO_EN, crear_logica, enviar, sembrar_operacion
from pruebas.utilidades_web import crear_usuario, crear_web, entrar
from web.modelos.cita import franjas_ofrecibles
from web.modelos.usuario import Rol
from web.repositorios.repositorio_citas import RepositorioCitas

UN_DIA_MS = 24 * 60 * 60 * 1000
CONTRASENA = "clave-citas-123"


@pytest.fixture()
def logica(tmp_path):
    prueba = crear_logica(tmp_path)
    yield prueba
    prueba.bd.cerrar()


def _cita(logica) -> tuple:  # type: ignore[no-untyped-def]
    with logica.bd.candado:
        return tuple(
            logica.bd.conexion.execute(
                "SELECT id, estado, cumplida_en_ventana FROM cita ORDER BY id DESC LIMIT 1"
            ).fetchone()
        )


def _turnos(logica) -> int:  # type: ignore[no-untyped-def]
    with logica.bd.candado:
        return int(logica.bd.conexion.execute("SELECT COUNT(*) FROM turno").fetchone()[0])


# --------------------------------------------------------- vencimiento §11.2


def test_vence_la_cita_programada_al_cerrar_su_ventana(logica) -> None:
    sembrar_operacion(logica, inicio_franja="07:30")  # ventana 07:30-07:50, ya cerrada
    vencidas = logica.nucleo.citas_svc.vencer_no_atendidas()
    cita_id, estado, en_ventana = _cita(logica)
    assert vencidas == [cita_id]
    assert (estado, en_ventana) == ("vencida", 0)  # §11.1 regla 8: incumplida
    publicada = logica.publicador.datos_de("cita.vencida")[-1]
    assert publicada["cita"] == cita_id and publicada["contenedor"] == "C01"
    assert logica.nucleo.citas_svc.vencer_no_atendidas() == []  # una sola vez


@pytest.mark.parametrize("inicio", ["08:00", "09:00"])
def test_no_vence_una_cita_con_ventana_abierta_o_futura(logica, inicio) -> None:
    sembrar_operacion(logica, inicio_franja=inicio)
    assert logica.nucleo.citas_svc.vencer_no_atendidas() == []
    assert _cita(logica)[1] == "programada"


def test_la_ventana_cierra_cinco_minutos_despues_del_fin(logica) -> None:
    sembrar_operacion(logica, inicio_franja="07:45")  # fin 08:00 → cierra 08:05
    assert logica.nucleo.citas_svc.vencer_no_atendidas() == []  # 08:03
    logica.reloj.avanzar_ms(3 * 60 * 1000)  # 08:06
    assert len(logica.nucleo.citas_svc.vencer_no_atendidas()) == 1


def test_no_vence_la_cita_de_un_vehiculo_que_ya_esta_en_la_terminal(logica) -> None:
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    logica.reloj.avanzar_ms(60 * 60 * 1000)
    assert logica.nucleo.citas_svc.vencer_no_atendidas() == []
    assert _cita(logica)[1] == "programada"  # A11: la decide el turno


# ------------------------------------------------ garita y ventana §11.1


def test_llegada_tarde_con_la_cita_vencida_de_hoy_ingresa_con_rt04(logica) -> None:
    """§11.1 regla 7: fuera de ventana es RT04, no rechazo, aunque la cita ya venció."""
    sembrar_operacion(logica, inicio_franja="07:30")
    logica.nucleo.citas_svc.vencer_no_atendidas()
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    turno = logica.nucleo.turnos_repo.activo_de_vehiculo(1)
    assert turno is not None
    retencion = logica.nucleo.retenciones.abierta_de_turno(turno.id)
    assert retencion is not None and retencion.causa.value == "RT04"
    assert _cita(logica)[1:] == ("vencida", 0)


def test_cita_vencida_de_otro_dia_ya_no_permite_ingresar(logica) -> None:
    sembrar_operacion(logica, inicio_franja="07:30")
    logica.nucleo.citas_svc.vencer_no_atendidas()
    logica.reloj.avanzar_ms(UN_DIA_MS)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    with logica.bd.candado:
        causa = logica.bd.conexion.execute(
            "SELECT causa FROM intento_ingreso ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert causa == "SIN_CITA" and _turnos(logica) == 0


def test_turno_anulado_cancela_su_cita_y_conserva_la_ventana(logica) -> None:
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    turno = logica.nucleo.turnos_repo.activo_de_vehiculo(1)
    logica.nucleo.maquina.anular(turno, "prueba", "web")
    assert _cita(logica)[1:] == ("cancelada", 1)  # A11: llegó en ventana


# ------------------------------------------------ acciones de TERMINAL §11.4


def test_terminal_no_cancela_ni_mueve_una_cita_en_uso(logica) -> None:
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    cita_id = _cita(logica)[0]
    citas = logica.nucleo.citas_svc
    assert citas.cancelar(cita_id) == (False, "CITA_EN_USO")
    assert citas.reprogramar(cita_id, "2026-09-20", "10:00") == (False, "CITA_EN_USO")


@pytest.mark.parametrize(
    ("fecha", "inicio", "motivo"),
    [
        ("2026-09-20", "07:00", "FRANJA_PASADA"),
        ("2026-09-20", "08:07", "FRANJA_INVALIDA"),
        ("2026-09-20", "25:00", "FRANJA_INVALIDA"),
        ("2026-02-30", "10:00", "FRANJA_INVALIDA"),
        ("20-09-2026", "10:00", "FRANJA_INVALIDA"),
    ],
)
def test_reprogramar_solo_a_una_franja_futura_y_bien_formada(logica, fecha, inicio, motivo) -> None:
    sembrar_operacion(logica, inicio_franja="09:00")
    cita_id = _cita(logica)[0]
    assert logica.nucleo.citas_svc.reprogramar(cita_id, fecha, inicio) == (False, motivo)


def test_bloquear_una_franja_vacia_impide_ofrecerla(logica) -> None:
    assert logica.nucleo.citas_svc.bloquear_franja("2026-09-20", "08:15")
    franja = next(f for f in logica.nucleo.citas_svc.agenda("2026-09-20") if f.inicio == "08:15")
    assert franja.bloqueada and franja.citas == []
    ocupacion = RepositorioCitas(logica.bd).ocupacion(["2026-09-20"])
    ofrecidas = [f.inicio for f in franjas_ofrecibles(logica.reloj(), ocupacion)]
    assert "08:15" not in ofrecidas and ofrecidas[0] == "08:30"


def test_agenda_marca_la_cita_en_uso(logica) -> None:
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    franja = next(f for f in logica.nucleo.citas_svc.agenda("2026-09-20") if f.inicio == "08:00")
    assert franja.citas[0].en_uso and franja.citas[0].cumplida_en_ventana is True


# ------------------------------------------------ cumplimiento y métrica 7


def test_indicador_del_dia_cuenta_solo_citas_con_resultado(logica) -> None:
    sembrar_operacion(logica, vehiculo="V01", contenedor="C01", inicio_franja="07:30")
    sembrar_operacion(logica, vehiculo="V02", contenedor="C02", inicio_franja="08:00")
    sembrar_operacion(logica, vehiculo="V03", contenedor="C03", inicio_franja="10:00")
    sembrar_operacion(logica, vehiculo="V04", contenedor="C04", inicio_franja="11:00")
    logica.nucleo.citas_svc.vencer_no_atendidas()  # V01 → vencida (0)
    enviar(logica, "garita.identificacion", {"veh": "V02"}, seq=1)  # en ventana (1)
    with logica.bd.candado:
        cita_v04 = logica.bd.conexion.execute("SELECT MAX(id) FROM cita").fetchone()[0]
    logica.nucleo.citas_svc.cancelar(cita_v04)  # cancelada sin resultado
    assert logica.nucleo.citas_svc.cumplimiento("2026-09-20") == (1, 2)  # V03 aún pendiente


def test_metrica_7_toma_la_franja_y_no_la_fecha_de_alta(logica) -> None:
    sembrar_operacion(logica)  # la cita se dio de alta 13:00 UTC; franja 08:00 local
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    reporte = logica.nucleo.reportes_svc.generar(
        "franja", "2026-09-20T14:00:00.000Z", "2026-09-20T14:30:00.000Z", generado_por=None
    )
    assert reporte.resultado["porcentaje_citas_cumplidas_en_ventana"] == 100.0
    fuera = logica.nucleo.reportes_svc.generar(
        "alta", "2026-09-20T12:00:00.000Z", "2026-09-20T13:30:00.000Z", generado_por=None
    )
    assert fuera.resultado["porcentaje_citas_cumplidas_en_ventana"] == 0.0


# ------------------------------------------------ barrera 🔴 4 y API


def test_ninguna_ruta_de_la_plataforma_crea_citas(tmp_path) -> None:
    """La cita solo nace del canal de mensajería (§11, hito H3 retirado)."""
    web = crear_web(tmp_path)
    rutas = {
        regla.rule
        for regla in web.app.url_map.iter_rules()
        if "/citas" in regla.rule and "POST" in (regla.methods or set())
    }
    assert rutas == {"/api/citas/<int:cita_id>/cancelar", "/api/citas/<int:cita_id>/reprogramar"}
    web.bd.cerrar()


def test_api_de_agenda_responde_errores_explicitos(tmp_path) -> None:
    web = crear_web(tmp_path)
    crear_usuario(web, "terminal01", Rol.TERMINAL, CONTRASENA)
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    mal_formada = cliente.post("/api/citas/1/reprogramar", json={"fecha": "x", "inicio": "8"})
    assert mal_formada.status_code == 422
    assert mal_formada.get_json()["error"] == "FRANJA_INVALIDA"
    inexistente = cliente.post("/api/citas/999/cancelar", json={})
    assert inexistente.status_code == 404
    assert cliente.post("/api/franjas/2026-09-20/08:07/bloquear", json={}).status_code == 422
    assert cliente.post("/api/franjas/2030-01-01/10:00/bloquear", json={}).status_code == 200
    web.bd.cerrar()


def test_la_herramienta_demo_solo_crea_cita_con_bandera_explicita(tmp_path) -> None:
    web = crear_web(Path(tmp_path))
    ruta_bd = web.app.extensions["contexto_portus"].configuracion.ruta_bd
    web.usuarios.crear("transportista01", "x", Rol.TRANSPORTISTA, "Transportista 1", CREADO_EN)
    web.usuarios.crear("naviera01", "x", Rol.NAVIERA, "Naviera A", CREADO_EN)
    crear_datos(ruta_bd)
    assert crear_operacion(ruta_bd) == 0
    with web.bd.candado:
        assert web.bd.conexion.execute("SELECT COUNT(*) FROM cita").fetchone()[0] == 0
    assert crear_operacion(ruta_bd, OpcionesDemo(con_cita=True)) == 0
    with web.bd.candado:
        assert web.bd.conexion.execute("SELECT COUNT(*) FROM cita").fetchone()[0] == 1
    web.bd.cerrar()
