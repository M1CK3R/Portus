"""Etapa 12: métricas y reportes (SPECS §16.1, §16.3, A15, A16).

La serie conocida de §16.2 vive en ``test_servicio_reportes``; aquí se prueba
lo que la completa: rango en hora de la terminal, fuente de la fila de espera
(A15), distancia en posiciones (A16), inicio real del ciclo, CSV con la
política en cada fila y reportes guardados. Reloj falso: 2026-09-20 14:03:22 UTC
= 08:03 en la terminal.
"""

import csv
import io

import pytest

from herramientas.enclavamientos_simulados import EstadoFisico, fijar_sensor, resumen
from pruebas.utilidades_logica import crear_logica, enviar, sembrar_operacion
from pruebas.utilidades_web import crear_usuario, crear_web, entrar
from web.modelos.ciclo_grua import ResultadoCiclo, distancia_de_ciclo, indice_de_extremo
from web.modelos.reporte import CLAVE_UNIDADES, METRICAS, ErrorRango, normalizar_rango
from web.modelos.trabajos import TipoTrabajo
from web.modelos.turno import EstadoTurno
from web.modelos.usuario import Rol
from web.repositorios.repositorio_telemetria import RepositorioTelemetria
from web.repositorios.repositorio_trabajos import RepositorioTrabajos
from web.servicios.exportacion_reportes import COLUMNAS_DETALLE, csv_detalle, csv_metricas

POSICIONES = ("P1", "P2", "P3", "P4")
CONTRASENA = "clave-reportes-123"


@pytest.fixture()
def logica(tmp_path):
    prueba = crear_logica(tmp_path)
    yield prueba
    prueba.bd.cerrar()


def _filas_csv(texto: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(texto)))


# ------------------------------------------------------- rango (zona horaria)


def test_rango_sin_zona_se_lee_en_hora_de_la_terminal() -> None:
    assert normalizar_rango("2026-09-20T08:00", "2026-09-20T09:30") == (
        "2026-09-20T14:00:00.000Z",
        "2026-09-20T15:30:00.000Z",
    )


def test_rango_con_zona_se_respeta() -> None:
    assert normalizar_rango("2026-09-20T14:00:00.000Z", "2026-09-20T09:30-06:00") == (
        "2026-09-20T14:00:00.000Z",
        "2026-09-20T15:30:00.000Z",
    )


@pytest.mark.parametrize(
    ("inicio", "fin", "codigo"),
    [
        ("2026-09-20T09:00", "2026-09-20T08:00", "RANGO_INVERTIDO"),
        ("2026-09-20T09:00", "2026-09-20T09:00", "RANGO_INVERTIDO"),
        ("ayer", "2026-09-20T08:00", "RANGO_INVALIDO"),
    ],
)
def test_rango_invalido_o_invertido_se_rechaza(inicio, fin, codigo) -> None:
    with pytest.raises(ErrorRango) as error:
        normalizar_rango(inicio, fin)
    assert error.value.codigo == codigo


def test_el_reporte_toma_el_periodo_local_y_no_seis_horas_antes(logica) -> None:
    """Auditoría #3: un turno cerrado 08:00-08:06 local debe caer en el rango 07:30-08:30."""
    turno = _turno_cerrado(logica, "2026-09-20T14:00:00.000Z", "2026-09-20T14:06:00.000Z")
    assert turno is not None
    reporte = logica.nucleo.reportes_svc.generar(
        "local", "2026-09-20T07:30", "2026-09-20T08:30", generado_por=None
    )
    assert (reporte.inicio, reporte.fin) == (
        "2026-09-20T13:30:00.000Z",
        "2026-09-20T14:30:00.000Z",
    )
    assert reporte.resultado["tiempo_promedio_camion_terminal_min"] == 6.0


# ------------------------------------------------ métrica 6: fila de espera (A15)


def _latido(logica, espera: int, seq: int) -> None:  # type: ignore[no-untyped-def]
    enviar(
        logica,
        "estado.latido",
        {"modo": "NORMAL", "grua": "REPOSO", "vehiculos_en_espera": espera, "enlace": True},
        seq=seq,
        id_evento=f"latido-{seq}",
    )


def _muestras(logica) -> list[int]:  # type: ignore[no-untyped-def]
    with logica.bd.candado:
        filas = logica.bd.conexion.execute(
            "SELECT CAST(valor AS INTEGER) FROM telemetria WHERE tipo = 'fila_espera'"
        ).fetchall()
    return sorted(int(f[0]) for f in filas)


def test_el_latido_alimenta_la_fila_de_espera_solo_cuando_cambia(logica) -> None:
    for seq, espera in enumerate([2, 2, 5, 5, 1], start=1):
        _latido(logica, espera, seq)
    assert _muestras(logica) == [1, 2, 5]
    reporte = logica.nucleo.reportes_svc.generar(
        "fila", "2026-09-20T08:00", "2026-09-20T08:10", generado_por=None
    )
    assert reporte.resultado["longitud_maxima_fila_espera"] == 5


def test_la_fila_vigente_al_empezar_el_periodo_tambien_cuenta(logica) -> None:
    RepositorioTelemetria(logica.bd).registrar_fila_espera(4, "2026-09-20T13:00:00.000Z")  # 07:00
    RepositorioTelemetria(logica.bd).registrar_fila_espera(1, "2026-09-20T14:20:00.000Z")  # 08:20
    maximo = RepositorioTelemetria(logica.bd).max_fila_espera_en_rango(
        "2026-09-20T14:00:00.000Z", "2026-09-20T15:00:00.000Z"
    )
    assert maximo == 4  # a las 08:00 seguían los 4 de las 07:00


def test_latido_sin_espera_o_invalido_no_deja_muestra(logica) -> None:
    enviar(logica, "estado.latido", {"modo": "NORMAL", "grua": "REPOSO"}, seq=1)
    enviar(logica, "estado.latido", {"vehiculos_en_espera": -3}, seq=2)
    assert _muestras(logica) == []


def test_el_simulador_reporta_la_fila_en_el_latido() -> None:
    fisico = EstadoFisico()
    fijar_sensor("espera", "3", fisico)
    assert fisico.vehiculos_en_espera == 3 and "espera=3" in resumen(fisico)


# ------------------------------------------- métrica 3: distancia (A16) y ciclo


@pytest.mark.parametrize(
    ("desde", "origen", "destino", "resultado", "esperado"),
    [
        (None, "VEH", "P1/N1", ResultadoCiclo.COMPLETADO, 1),
        ("P2/N1", "P4/N2", "VEH", ResultadoCiclo.COMPLETADO, 6),  # 2 en vacío + 4 cargado
        ("P2/N1", "P4/N2", "VEH", ResultadoCiclo.ABORTADO, 2),  # solo la aproximación
        ("VEH", "P3/N1", "P1/N1", ResultadoCiclo.COMPLETADO, 5),
    ],
)
def test_distancia_de_ciclo_en_posiciones(desde, origen, destino, resultado, esperado) -> None:
    assert distancia_de_ciclo(desde, origen, destino, resultado, POSICIONES) == esperado


def test_posicion_fuera_del_catalogo_cae_en_la_zona_de_transferencia() -> None:
    assert indice_de_extremo("P9/N1", POSICIONES) == 0
    assert indice_de_extremo("P3/N2", POSICIONES) == 3


def test_el_ciclo_real_empieza_al_enviar_el_job_y_mide_su_distancia(logica) -> None:
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    enviar(
        logica,
        "pesaje.medicion",
        {"veh": "V01", "peso_g": 38_600, "muestras": 10, "meseta": True},
        seq=2,
    )
    logica.reloj.avanzar_ms(2 * 60 * 1000)  # el JOB sale 2 min después de planificarse
    enviar(logica, "transferencia.evento", {"evento": "ALINEADO", "veh": "V01"}, seq=3)
    enviar(
        logica,
        "patio.cambio",
        {"posicion": "P1", "nivel": 1, "contenedor": "C01", "estado": "OCUPADA"},
        seq=4,
    )
    enviar(logica, "grua.paso", {"paso": "FIN", "resultado": "OK", "contenedor": "C01"}, seq=5)
    ciclo = RepositorioTrabajos(logica.bd).ciclos_ultimos(1)[0]
    assert ciclo.ts_inicio == "2026-09-20T14:05:22.418Z"  # envío del JOB, no la planificación
    assert ciclo.resultado is ResultadoCiclo.COMPLETADO
    assert ciclo.distancia_traslacion == 1  # zona de transferencia → P1


def test_metrica_1_cuenta_solo_remociones_completadas(logica) -> None:
    trabajos = RepositorioTrabajos(logica.bd)
    turno = _turno_cerrado(
        logica, "2026-09-20T14:00:00.000Z", "2026-09-20T14:09:00.000Z", tipo_op="RETIRO"
    )
    for resultado in (ResultadoCiclo.ABORTADO, ResultadoCiclo.COMPLETADO):
        trabajos.registrar_ciclo(
            turno,
            None,
            TipoTrabajo.REMOCION,
            "2026-09-20T14:02:00.000Z",
            "2026-09-20T14:03:00.000Z",
            2,
            resultado,
            "2026-09-20T14:03:00.000Z",
        )
    r = logica.nucleo.reportes_svc.generar(
        "remociones", "2026-09-20T07:55", "2026-09-20T08:15", generado_por=None
    ).resultado
    assert r["remociones_por_contenedor_retirado"] == 1.0  # el abortado no cuenta
    assert r["distancia_total_recorrida"] == 4  # la grúa sí recorrió ambos
    assert r[CLAVE_UNIDADES]["distancia_total_recorrida"] == "posiciones"


# --------------------------------------------------------------- CSV y API


def test_csv_de_detalle_lleva_la_politica_y_protege_formulas(logica) -> None:
    turno = _turno_cerrado(logica, "2026-09-20T13:00:00.000Z", "2026-09-20T14:10:00.000Z")
    logica.nucleo.turnos_repo.actualizar_datos(turno, {"motivo_anulacion": "=HIPERVINCULO(1)"})
    reporte = logica.nucleo.reportes_svc.generar(
        "csv", "2026-09-20T08:00", "2026-09-20T08:30", generado_por=None
    )
    texto = csv_detalle(reporte, logica.nucleo.reportes_svc.detalle_de_turnos(reporte))
    filas = _filas_csv(texto)
    assert tuple(filas[0].keys()) == COLUMNAS_DETALLE
    assert len(filas) == 1  # empezó antes del rango pero cerró dentro: es del periodo
    fila = filas[0]
    assert fila["politica_asignacion"] == "FASE1" and fila["reporte"] == str(reporte.id)
    assert fila["tiempo_terminal_min"] == "70.00"
    assert fila["motivo_anulacion"] == "'=HIPERVINCULO(1)"


def test_csv_de_metricas_una_fila_por_metrica_con_unidad(logica) -> None:
    reporte = logica.nucleo.reportes_svc.generar(
        "resumen", "2026-09-20T08:00", "2026-09-20T09:00", generado_por=None
    )
    filas = _filas_csv(csv_metricas(reporte))
    assert [f["metrica"] for f in filas] == list(METRICAS[:7])  # la 8 sin retenciones: vacía
    distancia = next(f for f in filas if f["metrica"] == "distancia_total_recorrida")
    assert distancia["unidad"] == "posiciones" and distancia["politica_asignacion"] == "FASE1"


def test_api_de_reportes_valida_lista_recupera_y_exporta(tmp_path) -> None:
    web = crear_web(tmp_path)
    crear_usuario(web, "terminal01", Rol.TERMINAL, CONTRASENA)
    cliente = web.app.test_client()
    entrar(cliente, "terminal01", CONTRASENA)
    invertido = cliente.post(
        "/api/reportes",
        json={"etiqueta": "x", "inicio": "2026-09-20T09:00", "fin": "2026-09-20T08:00"},
    )
    assert invertido.status_code == 422 and invertido.get_json()["error"] == "RANGO_INVERTIDO"
    creado = cliente.post(
        "/api/reportes",
        json={"etiqueta": "evaluación", "inicio": "2026-09-20T08:00", "fin": "2026-09-20T09:00"},
    ).get_json()["reporte"]
    assert creado["inicio"] == "2026-09-20T14:00:00.000Z" and creado["politica"] == "FASE1"
    listado = cliente.get("/api/reportes").get_json()["reportes"]
    assert [r["id"] for r in listado] == [creado["id"]]
    assert cliente.get(f"/api/reportes/{creado['id']}").status_code == 200
    assert cliente.get("/api/reportes/999").status_code == 404
    metricas = cliente.get(f"/api/reportes/{creado['id']}/exportar?contenido=metricas")
    assert metricas.mimetype == "text/csv" and b"politica_asignacion" in metricas.data
    detalle = cliente.get(f"/api/reportes/{creado['id']}/exportar")
    assert detalle.data.decode().startswith("reporte,etiqueta,politica_asignacion")
    otro = cliente.get(f"/api/reportes/{creado['id']}/exportar?contenido=pdf")
    assert otro.status_code == 422
    grua = cliente.get("/api/grua/exportar?inicio=2026-09-20T09:00&fin=2026-09-20T08:00")
    assert grua.status_code == 422
    web.bd.cerrar()


def _turno_cerrado(  # type: ignore[no-untyped-def]
    logica, creado: str, cerrado: str, tipo_op: str = "DEPOSITO"
) -> int:
    """Turno cerrado con las marcas dadas, sobre la operación sembrada de V01."""
    manifiesto_id = sembrar_operacion(logica, tipo_op=tipo_op)
    turnos = logica.nucleo.turnos_repo
    turno_id = turnos.crear(1, manifiesto_id, None, tipo_op, "verde", True, creado)
    turnos.actualizar_estado(turno_id, EstadoTurno.CERRADO, None)
    turnos.actualizar_datos(turno_id, {"cerrado_en": cerrado})
    return turno_id
