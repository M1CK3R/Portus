"""Pruebas del vigilante de latido §5.4 y de la AL01 retroactiva (A14)."""

from datetime import datetime, timedelta

from pruebas.utilidades_pruebas import INSTANTE_FIJO, MARCA_TIEMPO_FIJA
from puente.vigilante_latido import (
    EstadoEnlace,
    VigilanteLatido,
    datos_al01,
    evaluar_al01_retroactiva,
)

UMBRAL_MS = 15_000


def test_latidos_dentro_del_umbral_no_generan_transicion():
    vigilante = VigilanteLatido(umbral_ms=UMBRAL_MS, arranque_ms=0)
    for instante in (1_000, 6_000, 11_000):
        vigilante.registrar_latido(instante)
    assert vigilante.comprobar(14_000) is None
    assert vigilante.estado is EstadoEnlace.ACTIVO


def test_silencio_que_supera_tres_periodos_declara_enlace_perdido_una_vez():
    vigilante = VigilanteLatido(umbral_ms=UMBRAL_MS, arranque_ms=0)
    vigilante.registrar_latido(5_000)
    assert vigilante.comprobar(19_000) is None
    transicion = vigilante.comprobar(20_001)
    assert transicion is not None
    assert transicion.estado_nuevo is EstadoEnlace.PERDIDO
    assert transicion.ms_sin_latido >= UMBRAL_MS
    assert vigilante.comprobar(30_000) is None


def test_sin_latidos_desde_el_arranque_se_declara_perdido_al_cumplir_el_umbral():
    vigilante = VigilanteLatido(umbral_ms=UMBRAL_MS, arranque_ms=0)
    assert vigilante.comprobar(UMBRAL_MS - 1) is None
    transicion = vigilante.comprobar(UMBRAL_MS + 1)
    assert transicion is not None
    assert transicion.estado_nuevo is EstadoEnlace.PERDIDO


def test_latido_tras_la_perdida_recupera_el_estado_activo():
    vigilante = VigilanteLatido(umbral_ms=UMBRAL_MS, arranque_ms=0)
    vigilante.comprobar(UMBRAL_MS + 1)
    assert vigilante.estado is EstadoEnlace.PERDIDO
    vigilante.registrar_latido(UMBRAL_MS + 2)
    assert vigilante.estado is EstadoEnlace.ACTIVO
    assert vigilante.comprobar(UMBRAL_MS + 2 + UMBRAL_MS - 1) is None


def test_datos_de_al01_llevan_codigo_severidad_y_retroactiva_falsa():
    datos = datos_al01(16_000)
    assert datos["codigo"] == "AL01"
    assert datos["severidad"] == "CRITICA"
    assert datos["retroactiva"] is False
    assert datos["ms_sin_latido"] == 16_000


def test_al01_retroactiva_detecta_caida_previa_al_arrancar():
    ultimo = INSTANTE_FIJO - timedelta(seconds=120)
    marca = ultimo.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ultimo.microsecond // 1000:03d}Z"
    datos = evaluar_al01_retroactiva(marca, INSTANTE_FIJO, UMBRAL_MS)
    assert datos is not None
    assert datos["retroactiva"] is True
    assert datos["desde"] == marca
    assert datos["hasta"] == MARCA_TIEMPO_FIJA
    assert datos["ms_sin_latido"] == 120_000


def test_al01_retroactiva_sin_latido_previo_no_se_genera():
    assert evaluar_al01_retroactiva(None, INSTANTE_FIJO, UMBRAL_MS) is None


def test_al01_retroactiva_dentro_del_umbral_no_se_genera():
    ultimo = INSTANTE_FIJO - timedelta(seconds=10)
    marca = ultimo.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ultimo.microsecond // 1000:03d}Z"
    assert evaluar_al01_retroactiva(marca, INSTANTE_FIJO, UMBRAL_MS) is None


def test_al01_retroactiva_rechaza_marca_invalida():
    import pytest

    with pytest.raises(ValueError):
        evaluar_al01_retroactiva("no-es-fecha", INSTANTE_FIJO, UMBRAL_MS)


def test_hasta_de_la_al01_retroactiva_usa_formato_utc_iso():
    ultimo = INSTANTE_FIJO - timedelta(seconds=120)
    marca = ultimo.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ultimo.microsecond // 1000:03d}Z"
    datos = evaluar_al01_retroactiva(marca, INSTANTE_FIJO, UMBRAL_MS)
    assert datos is not None
    datetime.fromisoformat(str(datos["hasta"]).replace("Z", "+00:00"))
