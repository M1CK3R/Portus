"""Prueba de paridad de constantes firmware-puente y de configuración (P-2, A-7)."""

import json
from pathlib import Path

import pytest

from puente.configuracion import ConfiguracionPuente
from puente.mensajes_mqtt import (
    QOS_COMANDOS,
    QOS_EVENTOS,
    QOS_LATIDO,
    TOPIC_PREFIX,
    TOPICO_CMD_RESPUESTA,
    TOPICO_CMD_SOLICITUD,
    TOPICO_EVT_AGUJA,
    TOPICO_EVT_ALARMA,
    TOPICO_EVT_ESTADO,
    TOPICO_EVT_GARITA,
    TOPICO_EVT_GRUA,
    TOPICO_EVT_PATIO,
    TOPICO_EVT_PESAJE,
    TOPICO_EVT_SALIDA,
    TOPICO_EVT_TRANSFERENCIA,
    TOPICO_SRV_ALARMA,
    TOPICO_SRV_CITA,
    TOPICO_SRV_ENLACE,
    TOPICO_SRV_RETENCION,
    TOPICO_SRV_TURNO,
)
from puente.protocolo import (
    CAUSAS_RECHAZO_COMANDO,
    ESTADO_ACK,
    ESTADO_NAK,
    NOMBRES_COMANDOS,
    TIPOS_CONTROLADOR,
    TIPOS_EVENTO_CONTROLADOR,
    TIPOS_SERVIDOR,
    calcular_crc16,
)

RUTA_CONSTANTES = Path("docs/constantes_protocolo.json")


def _constantes() -> dict[str, object]:
    return json.loads(RUTA_CONSTANTES.read_text(encoding="utf-8"))


def test_vector_estandar_del_crc_coincide_con_la_fuente_compartida():
    vector = _constantes()["crc"]["vector_estandar"]
    assert f"{calcular_crc16(vector['datos'].encode()):04X}" == vector["crc_hex"]


def test_tipos_de_trama_coinciden_con_la_fuente_compartida():
    tipos = _constantes()["tipos_trama"]
    assert TIPOS_EVENTO_CONTROLADOR == set(tipos["eventos_controlador"])
    assert set(tipos["respuesta_controlador"]).issubset(TIPOS_CONTROLADOR)
    assert TIPOS_SERVIDOR == set(tipos["mensajes_servidor"])


def test_los_13_comandos_coinciden_con_la_fuente_compartida():
    assert NOMBRES_COMANDOS == set(_constantes()["comandos"])
    assert len(NOMBRES_COMANDOS) == 13


def test_causas_de_rechazo_coinciden_con_la_fuente_compartida():
    assert CAUSAS_RECHAZO_COMANDO == set(_constantes()["causas_rechazo_comando"])


def test_estados_de_respuesta_y_severidades_coinciden():
    constantes = _constantes()
    assert {ESTADO_ACK, ESTADO_NAK} == set(constantes["estados_respuesta"])
    assert constantes["severidades_alarma"] == ["CRITICA", "ALTA", "MEDIA", "BAJA"]


def test_topicos_del_espacio_obligatorio_coinciden_con_la_fuente_compartida():
    constantes = _constantes()
    topicos = constantes["topicos"]
    prefijo = constantes["prefijo_topicos"]
    assert TOPIC_PREFIX == prefijo == "portus"
    construidos = (
        {f"{TOPIC_PREFIX}/evt/{sufijo}" for sufijo in topicos["evt"]}
        | {f"{TOPIC_PREFIX}/cmd/{sufijo}" for sufijo in topicos["cmd"]}
        | {f"{TOPIC_PREFIX}/srv/{sufijo}" for sufijo in topicos["srv"]}
    )
    definidos = {
        TOPICO_EVT_GARITA,
        TOPICO_EVT_PESAJE,
        TOPICO_EVT_AGUJA,
        TOPICO_EVT_TRANSFERENCIA,
        TOPICO_EVT_GRUA,
        TOPICO_EVT_PATIO,
        TOPICO_EVT_SALIDA,
        TOPICO_EVT_ALARMA,
        TOPICO_EVT_ESTADO,
        TOPICO_CMD_SOLICITUD,
        TOPICO_CMD_RESPUESTA,
        TOPICO_SRV_TURNO,
        TOPICO_SRV_RETENCION,
        TOPICO_SRV_ALARMA,
        TOPICO_SRV_CITA,
        TOPICO_SRV_ENLACE,
    }
    assert construidos == definidos


def test_qos_y_tiempos_coinciden_con_la_fuente_compartida():
    constantes = _constantes()
    assert constantes["qos"] == {
        "eventos": QOS_EVENTOS,
        "latido": QOS_LATIDO,
        "comandos": QOS_COMANDOS,
    }
    tiempos = constantes["tiempos"]
    assert tiempos["periodo_latido_s"] == 5
    assert tiempos["periodos_sin_latido"] == 3
    assert tiempos["tiempo_limite_comando_s"] == 2
    assert tiempos["periodo_ping_s"] == 3


def test_configuracion_por_omision_produce_umbral_de_tres_periodos():
    configuracion = ConfiguracionPuente.por_omision()
    assert configuracion.umbral_latido_ms == 15_000
    assert configuracion.tiempo_limite_comando_s == 2.0


def test_configuracion_desde_env_lee_todas_las_claves():
    texto = "\n".join(
        [
            "# comentario",
            "PUERTO_SERIE=/dev/ttyACM0",
            "BAUDIOS=9600",
            "MQTT_HOST=10.0.0.5",
            "MQTT_PUERTO=1884",
            "MQTT_USUARIO=otro",
            "MQTT_CONTRASENA=secreta",
            "RUTA_BD=/data/portus.db",
            "TIEMPO_LIMITE_COMANDO_S=3",
            "PERIODO_LATIDO_S=4",
            "PERIODOS_SIN_LATIDO=2",
            "PERIODO_PING_S=5",
            "NIVEL_REGISTRO=DEBUG",
        ]
    )
    configuracion = ConfiguracionPuente.desde_env(texto)
    assert configuracion.ruta_puerto_serie == "/dev/ttyACM0"
    assert configuracion.baudios == 9600
    assert configuracion.mqtt_host == "10.0.0.5"
    assert configuracion.mqtt_puerto == 1884
    assert configuracion.umbral_latido_ms == 8_000
    assert configuracion.nivel_registro == "DEBUG"


@pytest.mark.parametrize("clave,valor", [("BAUDIOS", "x"), ("MQTT_PUERTO", "y")])
def test_configuracion_rechaza_valores_no_numericos(clave, valor):
    with pytest.raises(ValueError, match=clave):
        ConfiguracionPuente.desde_env(f"{clave}={valor}")
