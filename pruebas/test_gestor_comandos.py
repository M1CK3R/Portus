"""Pruebas del flujo de comandos §6.4 y §4.5: correlación, timeout 2 s e idempotencia."""

from pruebas.utilidades_pruebas import RelojFalso
from puente.gestor_comandos import (
    GestorComandos,
    SolicitudComando,
)
from puente.protocolo import (
    CAUSA_COMANDO_DESCONOCIDO,
    CAUSA_SIN_RESPUESTA,
    ESTADO_ACK,
    ESTADO_NAK,
    ContadorSecuenciaServidor,
)
from puente.secuencia import EmisorTramasServidor

CMD_ID = "b7f3c2e0-5a1d-4c8e-9f21-3d6e8a90c411"


def _gestor_con_reloj(reloj: RelojFalso) -> GestorComandos:
    emisor = EmisorTramasServidor(ContadorSecuenciaServidor(seq_inicial=0))
    return GestorComandos(emisor, tiempo_limite_s=2.0, reloj_ms=reloj)


def _solicitud(nombre: str = "AbrirTalanquera", cmd_id: str = CMD_ID) -> SolicitudComando:
    return SolicitudComando(cmd_id=cmd_id, nombre=nombre, parametros={}, usuario="terminal")


def test_comando_valido_genera_trama_cmd_y_registra_espera():
    reloj = RelojFalso(inicial_ms=10_000)
    gestor = _gestor_con_reloj(reloj)
    despacho = gestor.enviar_solicitud(_solicitud())
    assert despacho.trama_enviada is not None
    assert despacho.trama_enviada.seq == 1
    assert "nombre=AbrirTalanquera" in despacho.trama_enviada.armar_linea()


def test_respuesta_ack_resuelve_el_comando_sin_nak_sintetico():
    reloj = RelojFalso(inicial_ms=10_000)
    gestor = _gestor_con_reloj(reloj)
    despacho = gestor.enviar_solicitud(_solicitud())
    assert despacho.trama_enviada is not None
    reloj.avanzar(500)
    respuesta = gestor.resolver_respuesta(despacho.trama_enviada.seq, ESTADO_ACK, None)
    assert respuesta is not None
    assert respuesta.estado == ESTADO_ACK
    assert respuesta.sintetica is False
    assert respuesta.tardia is False
    assert gestor.expirar_esperas() == []


def test_comando_sin_respuesta_vence_a_los_dos_segundos_una_sola_vez():
    reloj = RelojFalso(inicial_ms=10_000)
    gestor = _gestor_con_reloj(reloj)
    despacho = gestor.enviar_solicitud(_solicitud())
    assert despacho.trama_enviada is not None
    reloj.avanzar(1999)
    assert gestor.expirar_esperas() == []
    reloj.avanzar(1)
    sinteticas = gestor.expirar_esperas()
    assert len(sinteticas) == 1
    sintetica = sinteticas[0]
    assert sintetica.estado == ESTADO_NAK
    assert sintetica.causa == CAUSA_SIN_RESPUESTA
    assert sintetica.cmd_id == CMD_ID
    assert sintetica.sintetica is True
    assert gestor.expirar_esperas() == []


def test_respuesta_tardia_tras_nak_sintetico_se_marca_como_tardia():
    reloj = RelojFalso(inicial_ms=10_000)
    gestor = _gestor_con_reloj(reloj)
    despacho = gestor.enviar_solicitud(_solicitud())
    assert despacho.trama_enviada is not None
    reloj.avanzar(2_500)
    assert len(gestor.expirar_esperas()) == 1
    tardia = gestor.resolver_respuesta(despacho.trama_enviada.seq, ESTADO_ACK, None)
    assert tardia is not None
    assert tardia.tardia is True
    assert tardia.estado == ESTADO_ACK


def test_duplicado_en_vuelo_no_reenvia_ni_duplica_espera():
    reloj = RelojFalso(inicial_ms=10_000)
    gestor = _gestor_con_reloj(reloj)
    primero = gestor.enviar_solicitud(_solicitud())
    duplicado = gestor.enviar_solicitud(_solicitud())
    assert primero.trama_enviada is not None
    assert duplicado.trama_enviada is None
    assert duplicado.respuesta_inmediata is None


def test_reintento_del_mismo_cmd_id_reutiliza_la_misma_seq():
    reloj = RelojFalso(inicial_ms=10_000)
    gestor = _gestor_con_reloj(reloj)
    primero = gestor.enviar_solicitud(_solicitud())
    assert primero.trama_enviada is not None
    reloj.avanzar(2_500)
    gestor.expirar_esperas()
    reintento = gestor.enviar_solicitud(_solicitud())
    assert reintento.trama_enviada is not None
    assert reintento.trama_enviada.seq == primero.trama_enviada.seq


def test_comando_desconocido_genera_nak_inmediato_sin_trama_serial():
    reloj = RelojFalso(inicial_ms=10_000)
    gestor = _gestor_con_reloj(reloj)
    despacho = gestor.enviar_solicitud(_solicitud(nombre="EncenderLuces"))
    assert despacho.trama_enviada is None
    assert despacho.respuesta_inmediata is not None
    assert despacho.respuesta_inmediata.causa == CAUSA_COMANDO_DESCONOCIDO
    assert despacho.respuesta_inmediata.estado == ESTADO_NAK


def test_rsp_sin_comando_pendiente_no_genera_respuesta():
    reloj = RelojFalso(inicial_ms=10_000)
    gestor = _gestor_con_reloj(reloj)
    assert gestor.resolver_respuesta(999, ESTADO_ACK, None) is None
