"""Reportes: las 8 métricas de §16.1 sobre la serie conocida de §16.2."""

from pruebas.utilidades_logica import crear_logica
from web.modelos.ciclo_grua import ResultadoCiclo
from web.modelos.retencion import CausaRetencion
from web.modelos.trabajos import TipoTrabajo
from web.modelos.usuario import Rol
from web.repositorios.repositorio_citas import RepositorioCitas
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_retenciones import RepositorioRetenciones
from web.repositorios.repositorio_telemetria import RepositorioTelemetria
from web.repositorios.repositorio_trabajos import RepositorioTrabajos
from web.repositorios.repositorio_turnos import RepositorioTurnos
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.repositorios.repositorio_vehiculos import RepositorioVehiculos

INICIO = "2026-09-20T00:00:00.000Z"
FIN = "2026-09-20T23:59:59.000Z"


def _sembrar_serie(logica) -> None:  # type: ignore[no-untyped-def]
    bd = logica.bd
    usuarios = RepositorioUsuarios(bd)
    # Naviera y transportista para los manifiestos.
    if usuarios.con_hash_por_username("naviera-r") is None:
        usuarios.crear("naviera-r", "x", Rol.NAVIERA, "Naviera R", "2026-09-01T00:00:00.000Z")
    if usuarios.con_hash_por_username("tr-r") is None:
        usuarios.crear("tr-r", "x", Rol.TRANSPORTISTA, "TR R", "2026-09-01T00:00:00.000Z")
    naviera_id = usuarios.con_hash_por_username("naviera-r")[0].id
    tr_id = usuarios.con_hash_por_username("tr-r")[0].id
    manifiestos = RepositorioManifiestos(bd)
    vehiculos = RepositorioVehiculos(bd)
    turnos = RepositorioTurnos(bd)
    trabajos = RepositorioTrabajos(bd)
    retenciones = RepositorioRetenciones(bd)
    citas = RepositorioCitas(bd)
    telemetria = RepositorioTelemetria(bd)

    def turno(n, cont, veh, op, creado, cerrado):  # type: ignore[no-untyped-def]
        with bd.candado:
            bd.conexion.execute(
                "INSERT OR IGNORE INTO contenedor (id, descripcion) VALUES (?, '')", (cont,)
            )
            bd.conexion.commit()
        if vehiculos.buscar_por_identificador(veh) is None:
            vehiculos.crear(veh, tr_id, 950)
        manifiestos.crear_demo(cont, naviera_id, tr_id, op, 38_500, "2026-09-19T00:00:00.000Z")
        mid = manifiestos.vigentes_de_transportista(tr_id)[-1].id
        tid = turnos.crear(
            vehiculos.buscar_por_identificador(veh).id, mid, None, op, "verde", True, creado
        )
        turnos.actualizar_estado(
            tid, __import__("web.modelos.turno", fromlist=["EstadoTurno"]).EstadoTurno.CERRADO, None
        )
        turnos.actualizar_datos(tid, {"cerrado_en": cerrado})
        return tid

    # 4 turnos cerrados: T1/T2/T3 depósito (4,6,5 min), T4 retiro (9 min).
    t1 = turno(
        "T1", "C01", "V01", "DEPOSITO", "2026-09-20T10:00:00.000Z", "2026-09-20T10:04:00.000Z"
    )
    t2 = turno(
        "T2", "C02", "V02", "DEPOSITO", "2026-09-20T10:10:00.000Z", "2026-09-20T10:16:00.000Z"
    )
    t3 = turno(
        "T3", "C03", "V03", "DEPOSITO", "2026-09-20T10:20:00.000Z", "2026-09-20T10:25:00.000Z"
    )
    t4 = turno("T4", "C04", "V04", "RETIRO", "2026-09-20T10:30:00.000Z", "2026-09-20T10:39:00.000Z")

    # Ciclos: T1/T2/T3 = 1 cada uno (depósito); T4 = 1 remoción + 1 retiro = 2.
    for tid, ts in (
        (t1, "2026-09-20T10:03:00.000Z"),
        (t2, "2026-09-20T10:15:00.000Z"),
        (t3, "2026-09-20T10:24:00.000Z"),
    ):
        trabajos.registrar_ciclo(
            tid, None, TipoTrabajo.DEPOSITO, ts, ts, 0, ResultadoCiclo.COMPLETADO, ts
        )
    trabajos.registrar_ciclo(
        t4,
        None,
        TipoTrabajo.REMOCION,
        "2026-09-20T10:35:00.000Z",
        "2026-09-20T10:36:00.000Z",
        0,
        ResultadoCiclo.COMPLETADO,
        "2026-09-20T10:36:00.000Z",
    )
    trabajos.registrar_ciclo(
        t4,
        None,
        TipoTrabajo.RETIRO,
        "2026-09-20T10:38:00.000Z",
        "2026-09-20T10:39:00.000Z",
        0,
        ResultadoCiclo.COMPLETADO,
        "2026-09-20T10:39:00.000Z",
    )

    # 2 retenciones resueltas: RT01/Corregir (8 min), RT03/Rechazar (4 min).
    rid1 = retenciones.crear(
        t1, CausaRetencion.RT01, "pesaje_entrada", None, 38500, 45000, "2026-09-20T10:01:00.000Z"
    )
    retenciones.resolver(rid1, "CORREGIR", "correccion", None, tr_id, "2026-09-20T10:09:00.000Z")
    rid2 = retenciones.crear(
        t2, CausaRetencion.RT03, "pesaje_entrada", None, 38500, 38600, "2026-09-20T10:11:00.000Z"
    )
    retenciones.resolver(rid2, "RECHAZAR", "canal rojo", None, tr_id, "2026-09-20T10:15:00.000Z")

    # 5 citas, 4 cumplidas en ventana.
    for i in range(5):
        cont = f"CC{i}"
        with bd.candado:
            bd.conexion.execute(
                "INSERT OR IGNORE INTO contenedor (id, descripcion) VALUES (?, '')", (cont,)
            )
            bd.conexion.commit()
        manifiestos.crear_demo(
            cont, naviera_id, tr_id, "DEPOSITO", 1000, "2026-09-19T00:00:00.000Z"
        )
        with bd.candado:
            mid = bd.conexion.execute(
                "SELECT id FROM manifiesto WHERE contenedor_id = ?", (cont,)
            ).fetchone()[0]
        cid = citas.crear(mid, tr_id, "2026-09-20", f"1{i}:00", "2026-09-20T09:00:00.000Z")
        citas.marcar_ventana(cid, i < 4)  # 4 dentro, 1 fuera

    # Fila de espera máxima = 3.
    telemetria.registrar_fila_espera(3, "2026-09-20T10:30:00.000Z")


def test_las_ocho_metricas_sobre_la_serie_conocida(tmp_path) -> None:  # type: ignore[no-untyped-def]
    logica = crear_logica(tmp_path)
    _sembrar_serie(logica)
    reporte = logica.nucleo.reportes_svc.generar("corrida", INICIO, FIN, generado_por=None)
    r = reporte.resultado
    assert r["remociones_por_contenedor_retirado"] == 1.0  # 1/1
    assert r["ciclos_grua_por_operacion"] == 1.25  # 5/4
    assert r["distancia_total_recorrida"] == 0  # sin distancia reportada
    assert r["tiempo_promedio_camion_terminal_min"] == 6.0  # (4+6+5+9)/4
    assert r["tiempo_promedio_retencion_min"] == 6.0  # (8+4)/2
    assert r["longitud_maxima_fila_espera"] == 3
    assert r["porcentaje_citas_cumplidas_en_ventana"] == 80.0  # 4/5
    assert r["retenciones_por_causa_y_resolucion"] == {"RT01/CORREGIR": 1, "RT03/RECHAZAR": 1}
    assert reporte.politica == "FASE1"  # §12.4, §16.3
