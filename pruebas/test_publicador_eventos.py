"""Pruebas del publicador de eventos: envoltorio único, QoS, retain y LWT (§5.2, §5.5)."""

from pruebas.utilidades_pruebas import SalidaFalsa
from puente.gestor_comandos import RespuestaComando
from puente.mensajes_mqtt import (
    TIPO_EVENTO_ALARMA_SERVIDOR,
    TOPICO_CMD_RESPUESTA,
    TOPICO_EVT_ESTADO,
    TOPICO_SRV_ALARMA,
    TOPICO_SRV_ENLACE,
)
from puente.protocolo import TIPO_EST, TIPO_GAR, TIPO_PES, Trama
from puente.publicador_eventos import PublicadorEventos
from puente.secuencia import ClaseSecuencia, EventoSecuencia
from puente.vigilante_latido import EstadoEnlace, datos_al01


def _publicador() -> tuple[PublicadorEventos, SalidaFalsa]:
    salida = SalidaFalsa()
    return PublicadorEventos(salida), salida


def test_envoltorio_del_latido_lleva_qos_cero_retain_y_campos_obligatorios():
    publicador, salida = _publicador()
    latido = Trama(
        seq=2210, tipo=TIPO_EST, campos={"modo": "NORMAL", "grua": "REPOSO", "link": "1"}
    )
    publicador.publicar_evento_controlador(latido)
    publicacion = salida.publicaciones[0]
    assert publicacion.topico == TOPICO_EVT_ESTADO
    assert publicacion.qos == 0
    assert publicacion.retain is True
    mensaje = publicacion.json()
    assert set(mensaje) == {"id", "ts", "origen", "tipo", "seq", "datos"}
    assert mensaje["origen"] == "controlador"
    assert mensaje["seq"] == 2210
    assert mensaje["datos"]["enlace"] is True


def test_evento_de_garita_lleva_qos_uno_sin_retain():
    publicador, salida = _publicador()
    publicador.publicar_evento_controlador(Trama(seq=9, tipo=TIPO_GAR, campos={"veh": "V01"}))
    publicacion = salida.publicaciones[0]
    assert publicacion.qos == 1
    assert publicacion.retain is False


def test_identificador_de_evento_es_determinista_por_seq_y_tipo():
    publicador, salida = _publicador()
    trama = Trama(
        seq=1042, tipo=TIPO_PES, campos={"veh": "V02", "g": "100", "n": "1", "meseta": "1"}
    )
    publicador.publicar_evento_controlador(trama)
    publicador.publicar_evento_controlador(trama)
    assert salida.publicaciones[0].json()["id"] == salida.publicaciones[1].json()["id"]


def test_respuesta_real_del_controlador_publica_cmd_respuesta():
    publicador, salida = _publicador()
    respuesta = RespuestaComando(
        cmd_id="abc",
        nombre="AbrirTalanquera",
        seq=57,
        estado="ACK",
        causa=None,
        sintetica=False,
        tardia=False,
    )
    publicador.publicar_respuesta_comando(respuesta)
    publicacion = salida.publicaciones[0]
    assert publicacion.topico == TOPICO_CMD_RESPUESTA
    assert publicacion.json()["datos"]["cmd_id"] == "abc"
    assert publicacion.json()["datos"]["estado"] == "ACK"
    assert publicacion.json()["datos"]["sintetica"] is False


def test_nak_sintetico_lleva_origen_puente_y_causa():
    publicador, salida = _publicador()
    respuesta = RespuestaComando(
        cmd_id="abc",
        nombre="AbrirTalanquera",
        seq=57,
        estado="NAK",
        causa="SIN_RESPUESTA",
        sintetica=True,
        tardia=False,
    )
    publicador.publicar_respuesta_comando(respuesta)
    mensaje = salida.publicaciones[0].json()
    assert mensaje["origen"] == "puente"
    assert mensaje["datos"]["causa"] == "SIN_RESPUESTA"


def test_salto_de_secuencia_se_publica_en_srv_enlace():
    publicador, salida = _publicador()
    evento = EventoSecuencia(clase=ClaseSecuencia.SALTO, seq=1045, seq_previa=1042, faltantes=2)
    publicador.publicar_salto_secuencia(evento)
    publicacion = salida.publicaciones[0]
    assert publicacion.topico == TOPICO_SRV_ENLACE
    assert publicacion.json()["tipo"] == "enlace.salto_secuencia"
    assert publicacion.json()["datos"]["faltantes"] == 2


def test_alarma_al01_publica_en_srv_alarma_con_origen_servidor():
    publicador, salida = _publicador()
    publicador.publicar_alarma_enlace(datos_al01(16_000))
    publicacion = salida.publicaciones[0]
    assert publicacion.topico == TOPICO_SRV_ALARMA
    mensaje = publicacion.json()
    assert mensaje["origen"] == "servidor"
    assert mensaje["tipo"] == TIPO_EVENTO_ALARMA_SERVIDOR
    assert mensaje["datos"]["codigo"] == "AL01"


def test_estado_de_enlace_publica_con_retain_en_srv_enlace():
    publicador, salida = _publicador()
    publicador.publicar_estado_enlace(
        EstadoEnlace.ACTIVO, "2026-09-20T14:03:22.418Z", {"tramas_validas": 3}
    )
    publicacion = salida.publicaciones[0]
    assert publicacion.topico == TOPICO_SRV_ENLACE
    assert publicacion.retain is True
    assert publicacion.json()["datos"]["puente"] == "activo"


def test_ultimo_testamento_declara_puente_caido():
    publicador, _ = _publicador()
    payload = publicador.armar_ultimo_testamento()
    assert '"puente":"caido"' in payload
