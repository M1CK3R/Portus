"""Pruebas de la configuración web: valores por omisión y lectura del .env (A-7)."""

import pytest

from web.configuracion.configuracion_web import (
    WEB_CLAVE_SECRETA_POR_OMISION,
    WEB_EXPIRACION_INACTIVIDAD_MIN_POR_OMISION,
    WEB_PUERTO_POR_OMISION,
    ConfiguracionWeb,
)


def test_por_omision_son_los_valores_documentados_en_el_env_ejemplo():
    configuracion = ConfiguracionWeb.por_omision()
    assert configuracion.puerto_web == WEB_PUERTO_POR_OMISION
    assert configuracion.expiracion_inactividad_min == WEB_EXPIRACION_INACTIVIDAD_MIN_POR_OMISION
    assert configuracion.expiracion_inactividad_s == 30 * 60
    assert configuracion.vida_maxima_sesion_s == 12 * 3600


def test_desde_env_lee_las_claves_web_y_conserva_el_resto():
    texto = (
        "# comentario\n"
        "WEB_PUERTO=9000\n"
        "WEB_CLAVE_SECRETA=una-clave-real\n"
        "WEB_EXPIRACION_INACTIVIDAD_MIN=15\n"
        "WEB_VIDA_MAXIMA_SESION_H=6\n"
        "NIVEL_REGISTRO=DEBUG\n"
    )
    configuracion = ConfiguracionWeb.desde_env(texto)
    assert configuracion.puerto_web == 9000
    assert configuracion.clave_secreta == "una-clave-real"
    assert configuracion.expiracion_inactividad_min == 15
    assert configuracion.vida_maxima_sesion_h == 6
    assert configuracion.nivel_registro == "DEBUG"


def test_sin_claves_web_se_usan_los_valores_por_omision():
    configuracion = ConfiguracionWeb.desde_env("PUERTO_SERIE=/dev/ttyUSB0\n")
    assert configuracion.puerto_web == WEB_PUERTO_POR_OMISION
    assert configuracion.clave_secreta == WEB_CLAVE_SECRETA_POR_OMISION
    assert configuracion.clave_de_desarrollo is True


def test_clave_real_no_se_marca_como_de_desarrollo():
    configuracion = ConfiguracionWeb.desde_env("WEB_CLAVE_SECRETA=clavedelsbc\n")
    assert configuracion.clave_de_desarrollo is False


def test_un_valor_no_numerico_falla_con_mensaje_explicito():
    with pytest.raises(ValueError, match="WEB_PUERTO"):
        ConfiguracionWeb.desde_env("WEB_PUERTO=http\n")
