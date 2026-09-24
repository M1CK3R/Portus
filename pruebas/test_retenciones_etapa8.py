"""Etapa 8 · Retenciones y parqueo (SPECS §10, §12.3, §13.1; ROADMAP Etapa 8).

Cubre las seis causas con su momento y rol, la asignación de las 3 plazas
(incluida la concurrente), las tres resoluciones con su restricción por rol,
la no re-resolución, Corregir con historial, la notificación de toda
resolución, parqueo lleno con riesgo (AL11), AL12 a los 30 min y el
inventario consistente tras Rechazar o anular (penalización §23.3).
"""

import threading
from datetime import timedelta

import pytest

from pruebas.utilidades_logica import (
    LogicaPrueba,
    crear_logica,
    enviar,
    sembrar_operacion,
)
from web.modelos.retencion import (
    DEFINICIONES_CAUSA,
    CausaRetencion,
    ResolucionRetencion,
    Retencion,
)
from web.modelos.turno import EstadoTurno
from web.modelos.usuario import Rol, Usuario
from web.planificador import TareaPeriodica
from web.repositorios.repositorio_plazas import ErrorPlaza
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.servicios.servicio_retenciones import (
    ErrorCorreccionNoAplica,
    ErrorMotivoRequerido,
    ErrorOrdenRetencion,
    ErrorPermisoResolucion,
    ErrorRetencionResuelta,
)
from web.servicios.servicio_turnos import ErrorTransicion

PESO_EN_TOLERANCIA_G = 38_600 + 950  # neto 38 600 g contra 38 500 declarados
PESO_FUERA_DE_TOLERANCIA_G = 45_000  # neto 44 050 g: 14 % sobre el declarado
MS_POR_MINUTO = 60_000


@pytest.fixture()
def logica(tmp_path):  # type: ignore[no-untyped-def]
    logica_prueba = crear_logica(tmp_path)
    yield logica_prueba
    logica_prueba.bd.cerrar()


def _usuario(logica: LogicaPrueba, rol: Rol) -> Usuario:
    """Usuario real del rol (FK de ``resuelta_por``)."""
    usuarios = RepositorioUsuarios(logica.bd)
    username = f"{rol.value.lower()}-prueba"
    if usuarios.con_hash_por_username(username) is None:
        usuarios.crear(username, "x", rol, username, "2026-09-20T13:00:00.000Z")
    return usuarios.con_hash_por_username(username)[0]


def _ingresar(logica: LogicaPrueba, vehiculo: str, peso_g: int, seq: int) -> None:
    """GAR y pesaje de entrada del vehículo (§9.4, §9.2)."""
    enviar(logica, "garita.identificacion", {"veh": vehiculo}, seq=seq)
    enviar(
        logica,
        "pesaje.medicion",
        {"veh": vehiculo, "peso_g": peso_g, "muestras": 10, "meseta": True},
        seq=seq + 1,
    )


def _retenido_por_rt01(logica: LogicaPrueba, vehiculo: str = "V01", seq: int = 1) -> Retencion:
    sembrar_operacion(logica, vehiculo=vehiculo, contenedor=vehiculo.replace("V", "C"))
    _ingresar(logica, vehiculo, PESO_FUERA_DE_TOLERANCIA_G, seq)
    return _abierta(logica, CausaRetencion.RT01)


def _abierta(logica: LogicaPrueba, causa: CausaRetencion) -> Retencion:
    return next(
        r
        for r in logica.nucleo.retenciones.listar(estado="abierta", causa=causa.value)
        if r.causa is causa
    )


def _contar(logica: LogicaPrueba, sql: str, parametros: tuple[object, ...] = ()) -> int:
    with logica.bd.candado:
        return int(logica.bd.conexion.execute(sql, parametros).fetchone()[0])


def _estado_posicion(logica: LogicaPrueba, posicion: str) -> str:
    return next(p.estado for p in logica.nucleo.patio.posiciones() if p.id == posicion)


# ------------------------------------------------------------ causas §10.2


@pytest.mark.parametrize(
    ("causa", "rol"),
    [
        (CausaRetencion.RT01, Rol.TERMINAL),
        (CausaRetencion.RT02, Rol.TERMINAL),
        (CausaRetencion.RT03, Rol.AUTORIDAD),
        (CausaRetencion.RT04, Rol.TERMINAL),
        (CausaRetencion.RT05, Rol.AUTORIDAD),
        (CausaRetencion.RT06, Rol.TERMINAL),
    ],
)
def test_cada_causa_tiene_el_rol_facultado_del_specs(causa, rol) -> None:  # type: ignore[no-untyped-def]
    assert DEFINICIONES_CAUSA[causa].rol_facultado is rol


def test_rt01_nace_tras_el_pesaje_de_entrada_con_plaza_y_aguja(logica) -> None:  # type: ignore[no-untyped-def]
    retencion = _retenido_por_rt01(logica)

    assert (retencion.estacion, retencion.plaza) == ("pesaje_entrada", 1)
    assert "AgujaParqueo" in logica.publicador.nombres_de_comandos()
    aviso = logica.publicador.datos_de("notificacion.vehiculo_retenido")[-1]
    assert aviso["causa"] == "RT01" and aviso["diferencia_g"] == 44_050 - 38_500


def test_rt03_canal_rojo_tras_pesaje_de_entrada(logica) -> None:  # type: ignore[no-untyped-def]
    sembrar_operacion(logica, canal="rojo")

    _ingresar(logica, "V01", PESO_EN_TOLERANCIA_G, seq=1)

    assert _abierta(logica, CausaRetencion.RT03).estacion == "pesaje_entrada"


def test_rt04_fuera_de_ventana_al_presentarse_en_garita(logica) -> None:  # type: ignore[no-untyped-def]
    sembrar_operacion(logica, inicio_franja="10:00")  # el reloj marca 08:03 local

    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)

    assert _abierta(logica, CausaRetencion.RT04).estacion == "garita"


def test_rt02_tras_pesaje_de_salida_sin_ramal(logica) -> None:  # type: ignore[no-untyped-def]
    _deposito_hasta_pesaje_de_salida(logica)
    aguja_antes = logica.publicador.nombres_de_comandos().count("AgujaParqueo")

    enviar(logica, "pesaje.medicion", {"veh": "V01", "peso_g": 5_000, "meseta": True}, seq=6)

    retencion = _abierta(logica, CausaRetencion.RT02)
    assert retencion.estacion == "pesaje_salida" and retencion.plaza == 1  # plaza lógica (A3)
    assert logica.publicador.nombres_de_comandos().count("AgujaParqueo") == aguja_antes


def _deposito_hasta_pesaje_de_salida(logica: LogicaPrueba) -> None:
    """Depósito completo hasta EnPesajeSalida: el contenedor ya está en P1/N1."""
    sembrar_operacion(logica)
    _ingresar(logica, "V01", PESO_EN_TOLERANCIA_G, seq=1)
    enviar(logica, "transferencia.evento", {"evento": "ALINEADO", "veh": "V01"}, seq=3)
    enviar(
        logica,
        "patio.cambio",
        {"posicion": "P1", "nivel": 1, "contenedor": "C01", "estado": "OCUPADA"},
        seq=4,
    )
    enviar(logica, "grua.paso", {"paso": "FIN", "resultado": "OK", "contenedor": "C01"}, seq=5)


# ---------------------------------------------------------- órdenes RT05/RT06


def test_autoridad_ordena_rt05_y_el_vehiculo_va_al_parqueo(logica) -> None:  # type: ignore[no-untyped-def]
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    turno = logica.nucleo.turnos_repo.activo_de_vehiculo(1)

    retencion = logica.nucleo.retenciones_svc.ordenar(
        turno.id, CausaRetencion.RT05, _usuario(logica, Rol.AUTORIDAD), "documento vencido"
    )

    assert (retencion.causa, retencion.estacion, retencion.plaza) == (
        CausaRetencion.RT05,
        "garita",
        1,
    )
    assert "AgujaParqueo" in logica.publicador.nombres_de_comandos()


@pytest.mark.parametrize(
    ("rol", "causa"),
    [(Rol.TERMINAL, CausaRetencion.RT05), (Rol.AUTORIDAD, CausaRetencion.RT06)],
)
def test_nadie_ordena_una_causa_ajena(logica, rol, causa) -> None:  # type: ignore[no-untyped-def]
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    turno = logica.nucleo.turnos_repo.activo_de_vehiculo(1)

    with pytest.raises(ErrorOrdenRetencion) as error:
        logica.nucleo.retenciones_svc.ordenar(turno.id, causa, _usuario(logica, rol))

    assert error.value.codigo == "ROL_NO_FACULTADO"


def test_retener_en_estado_no_retenible_no_toma_plaza(logica) -> None:  # type: ignore[no-untyped-def]
    sembrar_operacion(logica)
    _ingresar(logica, "V01", PESO_EN_TOLERANCIA_G, seq=1)  # queda EnRuta
    turno = logica.nucleo.turnos_repo.activo_de_vehiculo(1)

    with pytest.raises(ErrorOrdenRetencion) as orden:
        logica.nucleo.retenciones_svc.ordenar(
            turno.id, CausaRetencion.RT06, _usuario(logica, Rol.TERMINAL)
        )
    with pytest.raises(ErrorTransicion):
        logica.nucleo.retenciones_svc.retener(turno, CausaRetencion.RT06, "operacion")

    assert orden.value.codigo == "ESTADO_NO_RETENIBLE"
    assert all(p.turno_id is None for p in logica.plazas.todas())
    assert _contar(logica, "SELECT COUNT(*) FROM retencion") == 0


# ------------------------------------------------------------ plazas §10.1


def test_plazas_de_menor_numero_y_la_cuarta_retencion_genera_al11(logica) -> None:  # type: ignore[no-untyped-def]
    plazas = [_retenido_por_rt01(logica, f"V0{n}", seq=10 * n).plaza for n in range(1, 5)]

    assert plazas == [1, 2, 3, None]
    assert _contar(logica, "SELECT COUNT(*) FROM alarma WHERE codigo = 'AL11'") == 1


def test_parqueo_lleno_con_riesgo_rechaza_en_garita_y_genera_al11(logica) -> None:  # type: ignore[no-untyped-def]
    for n in range(1, 4):
        _retenido_por_rt01(logica, f"V0{n}", seq=10 * n)
    sembrar_operacion(logica, vehiculo="V04", contenedor="C04", canal="rojo")

    enviar(logica, "garita.identificacion", {"veh": "V04"}, seq=40)

    decision = logica.publicador.datos_de("turno.autorizacion")[-1]
    assert (decision["resultado"], decision["causa"]) == ("RECHAZADO", "PARQUEO_LLENO")
    assert _contar(logica, "SELECT COUNT(*) FROM turno") == 3  # §8.2 regla 1: sin turno
    assert _contar(logica, "SELECT COUNT(*) FROM alarma WHERE codigo = 'AL11'") == 1


def test_asignacion_concurrente_no_repite_plaza(logica) -> None:  # type: ignore[no-untyped-def]
    manifiesto_id = sembrar_operacion(logica)
    turnos = [
        logica.nucleo.turnos_repo.crear(1, manifiesto_id, None, "DEPOSITO", "verde", True, "t")
        for _ in range(6)
    ]
    asignadas: list[int] = []
    sin_plaza: list[int] = []
    salida = threading.Lock()
    barrera = threading.Barrier(len(turnos))

    def asignar(turno_id: int) -> None:
        barrera.wait()
        try:
            numero = logica.plazas.asignar(turno_id, "2026-09-20T14:03:22.418Z")
        except ErrorPlaza:
            with salida:
                sin_plaza.append(turno_id)
            return
        with salida:
            asignadas.append(numero)

    hilos = [threading.Thread(target=asignar, args=(t,)) for t in turnos]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert sorted(asignadas) == [1, 2, 3] and len(sin_plaza) == 3


# --------------------------------------------------------- resoluciones §10.3


@pytest.mark.parametrize(
    ("rol", "resolucion"),
    [
        (Rol.AUTORIDAD, ResolucionRetencion.ACLARAR),  # RT01 es de TERMINAL
        (Rol.AUTORIDAD, ResolucionRetencion.RECHAZAR),
        (Rol.NAVIERA, ResolucionRetencion.ACLARAR),
    ],
)
def test_un_rol_no_facultado_no_resuelve(logica, rol, resolucion) -> None:  # type: ignore[no-untyped-def]
    retencion = _retenido_por_rt01(logica)

    with pytest.raises(ErrorPermisoResolucion):
        logica.nucleo.retenciones_svc.resolver(
            retencion.id, resolucion, _usuario(logica, rol), motivo="x"
        )

    assert logica.nucleo.retenciones.buscar_por_id(retencion.id).estado == "abierta"


def test_la_autoridad_no_corrige_ni_la_terminal_resuelve_rt03(logica) -> None:  # type: ignore[no-untyped-def]
    sembrar_operacion(logica, canal="rojo")
    _ingresar(logica, "V01", PESO_EN_TOLERANCIA_G, seq=1)
    rt03 = _abierta(logica, CausaRetencion.RT03)
    servicio = logica.nucleo.retenciones_svc

    with pytest.raises(ErrorPermisoResolucion):
        servicio.resolver(rt03.id, ResolucionRetencion.CORREGIR, _usuario(logica, Rol.AUTORIDAD))
    with pytest.raises(ErrorPermisoResolucion):
        servicio.resolver(rt03.id, ResolucionRetencion.ACLARAR, _usuario(logica, Rol.TERMINAL))
    resuelta = servicio.resolver(
        rt03.id, ResolucionRetencion.ACLARAR, _usuario(logica, Rol.AUTORIDAD)
    )

    assert resuelta.resolucion == "ACLARAR"


def test_rechazar_exige_motivo_y_aclarar_no(logica) -> None:  # type: ignore[no-untyped-def]
    retencion = _retenido_por_rt01(logica)
    terminal = _usuario(logica, Rol.TERMINAL)

    with pytest.raises(ErrorMotivoRequerido):
        logica.nucleo.retenciones_svc.resolver(
            retencion.id, ResolucionRetencion.RECHAZAR, terminal, motivo="  "
        )
    resuelta = logica.nucleo.retenciones_svc.resolver(
        retencion.id, ResolucionRetencion.ACLARAR, terminal
    )

    assert resuelta.motivo is None


def test_una_retencion_resuelta_no_se_resuelve_de_nuevo(logica) -> None:  # type: ignore[no-untyped-def]
    retencion = _retenido_por_rt01(logica)
    terminal = _usuario(logica, Rol.TERMINAL)
    logica.nucleo.retenciones_svc.resolver(retencion.id, ResolucionRetencion.ACLARAR, terminal)

    with pytest.raises(ErrorRetencionResuelta):
        logica.nucleo.retenciones_svc.resolver(
            retencion.id, ResolucionRetencion.RECHAZAR, terminal, motivo="otra vez"
        )


def test_aclarar_devuelve_el_turno_y_libera_la_plaza_con_ack(logica) -> None:  # type: ignore[no-untyped-def]
    retencion = _retenido_por_rt01(logica)

    logica.nucleo.retenciones_svc.resolver(
        retencion.id, ResolucionRetencion.ACLARAR, _usuario(logica, Rol.TERMINAL)
    )
    cmd_id, parametros = logica.publicador.ultimo_comando("AgujaLiberar")
    enviar(logica, "comando.respuesta", {"cmd_id": cmd_id, "estado": "ACK"}, seq=9)

    turno = logica.nucleo.turnos_repo.buscar_por_id(retencion.turno_id)
    assert turno.estado is EstadoTurno.EN_RUTA  # mapa de regreso A2
    assert parametros == {"plaza": "1"}
    assert logica.plazas.todas()[0].turno_id is None


def test_corregir_sustituye_el_peso_y_guarda_el_anterior(logica) -> None:  # type: ignore[no-untyped-def]
    retencion = _retenido_por_rt01(logica)
    turno = logica.nucleo.turnos_repo.buscar_por_id(retencion.turno_id)

    logica.nucleo.retenciones_svc.resolver(
        retencion.id, ResolucionRetencion.CORREGIR, _usuario(logica, Rol.TERMINAL)
    )

    manifiesto = logica.manifiestos.buscar_por_id(turno.manifiesto_id)
    with logica.bd.candado:
        historial = logica.bd.conexion.execute(
            "SELECT valor_anterior, valor_nuevo, retencion_id FROM manifiesto_historial"
        ).fetchall()
    assert manifiesto.peso_declarado_g == 44_050
    assert [tuple(fila) for fila in historial] == [("38500", "44050", retencion.id)]
    aviso = logica.publicador.datos_de("notificacion.retencion_resuelta")[-1]
    assert aviso["nuevo_peso_declarado_g"] == 44_050


def test_corregir_no_aplica_cuando_se_comparo_con_la_tara(logica) -> None:  # type: ignore[no-untyped-def]
    _deposito_hasta_pesaje_de_salida(logica)
    enviar(logica, "pesaje.medicion", {"veh": "V01", "peso_g": 5_000, "meseta": True}, seq=6)
    rt02 = _abierta(logica, CausaRetencion.RT02)

    with pytest.raises(ErrorCorreccionNoAplica):
        logica.nucleo.retenciones_svc.resolver(
            rt02.id, ResolucionRetencion.CORREGIR, _usuario(logica, Rol.TERMINAL)
        )

    assert logica.nucleo.retenciones.buscar_por_id(rt02.id).estado == "abierta"


@pytest.mark.parametrize(
    "resolucion",
    [ResolucionRetencion.ACLARAR, ResolucionRetencion.CORREGIR, ResolucionRetencion.RECHAZAR],
)
def test_toda_resolucion_notifica_al_transportista(logica, resolucion) -> None:  # type: ignore[no-untyped-def]
    retencion = _retenido_por_rt01(logica)

    logica.nucleo.retenciones_svc.resolver(
        retencion.id, resolucion, _usuario(logica, Rol.TERMINAL), motivo="peso no coincide"
    )

    with logica.bd.candado:
        fila = logica.bd.conexion.execute(
            "SELECT usuario.username FROM notificacion "
            "JOIN usuario ON usuario.id = notificacion.transportista_id "
            "WHERE notificacion.tipo = 'retencion_resuelta'"
        ).fetchone()
    assert fila is not None and fila[0] == "tr-v01"  # solo al propietario (§15.3)


def test_rt01_en_canal_rojo_pasa_a_rt03_sin_salir_del_parqueo(logica) -> None:  # type: ignore[no-untyped-def]
    sembrar_operacion(logica, canal="rojo")
    _ingresar(logica, "V01", PESO_FUERA_DE_TOLERANCIA_G, seq=1)
    rt01 = _abierta(logica, CausaRetencion.RT01)

    logica.nucleo.retenciones_svc.resolver(
        rt01.id, ResolucionRetencion.ACLARAR, _usuario(logica, Rol.TERMINAL)
    )

    rt03 = _abierta(logica, CausaRetencion.RT03)
    turno = logica.nucleo.turnos_repo.buscar_por_id(rt01.turno_id)
    assert rt03.plaza == rt01.plaza and turno.estado is EstadoTurno.RETENIDO
    assert "AgujaLiberar" not in logica.publicador.nombres_de_comandos()


# ------------------------------------------------------ inventario §12.3 ⚠️


def test_rechazar_antes_de_la_grua_libera_la_reserva_y_cancela_trabajos(logica) -> None:  # type: ignore[no-untyped-def]
    retencion = _retenido_por_rt01(logica)
    assert _estado_posicion(logica, "P1") == "reservada"

    logica.nucleo.retenciones_svc.resolver(
        retencion.id,
        ResolucionRetencion.RECHAZAR,
        _usuario(logica, Rol.TERMINAL),
        motivo="sobrepeso",
    )

    turno = logica.nucleo.turnos_repo.buscar_por_id(retencion.turno_id)
    assert turno.estado is EstadoTurno.ANULADO
    assert _estado_posicion(logica, "P1") == "libre"
    assert logica.nucleo.trabajos_svc.quedan_pendientes(turno.id) is False
    assert {"AgujaLiberar", "AbrirPuertaSalida"} <= set(logica.publicador.nombres_de_comandos())
    anulado = logica.publicador.datos_de("notificacion.turno_anulado")[-1]
    assert anulado["resultado"] == "anulado" and "sobrepeso" in str(anulado["motivo"])


def test_rechazar_tras_mover_el_contenedor_conserva_la_posicion_fisica(logica) -> None:  # type: ignore[no-untyped-def]
    _deposito_hasta_pesaje_de_salida(logica)
    enviar(logica, "pesaje.medicion", {"veh": "V01", "peso_g": 5_000, "meseta": True}, seq=6)
    rt02 = _abierta(logica, CausaRetencion.RT02)

    logica.nucleo.retenciones_svc.resolver(
        rt02.id, ResolucionRetencion.RECHAZAR, _usuario(logica, Rol.TERMINAL), motivo="x"
    )

    celda = next(c for c in logica.nucleo.patio.celdas() if c.contenedor_id == "C01")
    assert (celda.posicion, celda.nivel) == ("P1", 1)  # §8.2 regla 4
    assert _estado_posicion(logica, "P1") == "ocupada"
    assert logica.plazas.todas()[0].turno_id is None  # sin ramal: plaza lógica libre


def test_anular_un_turno_retenido_exige_rechazar(logica) -> None:  # type: ignore[no-untyped-def]
    retencion = _retenido_por_rt01(logica)

    with pytest.raises(ErrorOrdenRetencion) as error:
        logica.nucleo.retenciones_svc.anular_turno(retencion.turno_id, "cliente desiste")

    assert error.value.codigo == "RETENCION_ABIERTA"


def test_anulacion_manual_libera_la_reserva(logica) -> None:  # type: ignore[no-untyped-def]
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    turno = logica.nucleo.turnos_repo.activo_de_vehiculo(1)

    logica.nucleo.retenciones_svc.anular_turno(turno.id, "cliente desiste")

    assert _estado_posicion(logica, "P1") == "libre"


def test_segundo_deposito_se_apila_en_nivel_2_y_libera_bien_su_reserva(logica) -> None:  # type: ignore[no-untyped-def]
    """Regresión E2E: la garita reservaba solo posiciones libres y fallaba al apilar."""
    _deposito_hasta_pesaje_de_salida(logica)  # C01 queda confirmado en P1/N1
    sembrar_operacion(logica, vehiculo="V02", contenedor="C02")

    enviar(logica, "garita.identificacion", {"veh": "V02"}, seq=20)

    turno = logica.nucleo.turnos_repo.activo_de_vehiculo(2)
    assert (turno.posicion_patio, turno.nivel) == ("P1", 2)
    assert _estado_posicion(logica, "P1") == "reservada"
    logica.nucleo.retenciones_svc.anular_turno(turno.id, "prueba")
    assert _estado_posicion(logica, "P1") == "ocupada"  # vuelve a lo confirmado


# ------------------------------------------------------------------- AL12


def test_al12_a_los_30_minutos_una_sola_vez_por_retencion(logica) -> None:  # type: ignore[no-untyped-def]
    retencion = _retenido_por_rt01(logica)
    vigilante = logica.nucleo.vigilante_retenciones

    logica.reloj.avanzar_ms(29 * MS_POR_MINUTO)
    antes = vigilante.revisar()
    logica.reloj.avanzar_ms(2 * MS_POR_MINUTO)
    primera = vigilante.revisar()
    segunda = vigilante.revisar()

    assert (antes, primera, segunda) == ([], [retencion.id], [])
    assert _contar(logica, "SELECT COUNT(*) FROM alarma WHERE codigo = 'AL12'") == 1
    assert logica.publicador.datos_de("alarma.servidor")[-1]["codigo"] == "AL12"


def test_al12_no_se_genera_para_retenciones_resueltas(logica) -> None:  # type: ignore[no-untyped-def]
    retencion = _retenido_por_rt01(logica)
    logica.nucleo.retenciones_svc.resolver(
        retencion.id, ResolucionRetencion.ACLARAR, _usuario(logica, Rol.TERMINAL)
    )

    logica.reloj.avanzar_ms(int(timedelta(hours=1).total_seconds() * 1000))

    assert logica.nucleo.vigilante_retenciones.revisar() == []


def test_tarea_periodica_sobrevive_a_una_pasada_fallida() -> None:
    llamadas: list[int] = []

    def fallar() -> None:
        llamadas.append(1)
        raise RuntimeError("fallo simulado")

    tarea = TareaPeriodica("prueba", 60, fallar)
    tarea.ejecutar_una_vez()
    tarea.ejecutar_una_vez()

    assert len(llamadas) == 2
