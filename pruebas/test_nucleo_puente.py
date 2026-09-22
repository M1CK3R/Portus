"""Pruebas de integración del núcleo del puente con fronteras falsas (T-5).

Cubre el flujo completo de la Etapa 3: recepción serial con rastreo de SEQ y
SYN (§4.2), publicación MQTT con el envoltorio único (§5), vigilancia del
latido con AL01 (§5.4) y flujo del comando con timeout de 2 s (§6.4, §4.5).
"""

import json

from pruebas.utilidades_pruebas import (
    INSTANTE_FIJO,
    MARCA_TIEMPO_FIJA,
    PuertoSerieFalso,
    RelojFalso,
    RelojUtcFalso,
    SalidaFalsa,
)
from puente.gestor_comandos import GestorComandos
from puente.nucleo_puente import NucleoPuente
from puente.persistencia_sqlite import PersistenciaSqlite
from puente.protocolo import Trama
from puente.publicador_eventos import PublicadorEventos
from puente.secuencia import ContadorSecuenciaServidor, EmisorTramasServidor
from puente.vigilante_latido import VigilanteLatido

CMD_ID = "b7f3c2e0-5a1d-4c8e-9f21-3d6e8a90c411"
UMBRAL_MS = 15_000


def _nucleo(
    tmp_path, reloj_utc: RelojUtcFalso | None = None, base_bd: str = "nucleo.db"
) -> tuple[NucleoPuente, PuertoSerieFalso, SalidaFalsa, RelojFalso]:
    puerto = PuertoSerieFalso()
    puerto.abrir()
    salida = SalidaFalsa()
    reloj = RelojFalso(inicial_ms=100_000)
    emisor = EmisorTramasServidor(ContadorSecuenciaServidor(seq_inicial=0))
    persistencia = PersistenciaSqlite(str(tmp_path / base_bd))
    nucleo = NucleoPuente(
        puerto=puerto,
        publicador=PublicadorEventos(salida),
        gestor=GestorComandos(emisor, tiempo_limite_s=2.0, reloj_ms=reloj),
        emisor=emisor,
        vigilante=VigilanteLatido(umbral_ms=UMBRAL_MS, arranque_ms=100_000),
        persistencia=persistencia,
        reloj_ms=reloj,
        reloj_utc=reloj_utc if reloj_utc is not None else lambda: INSTANTE_FIJO,
    )
    return nucleo, puerto, salida, reloj


def _solicitud_mqtt(nombre: str = "AbrirTalanquera", cmd_id: str = CMD_ID) -> bytes:
    contenido = {
        "id": "9f8b-llave",
        "ts": MARCA_TIEMPO_FIJA,
        "origen": "servidor",
        "tipo": "comando.solicitud",
        "seq": None,
        "datos": {"cmd_id": cmd_id, "nombre": nombre, "parametros": {}, "usuario": "terminal"},
    }
    return json.dumps(contenido).encode("utf-8")


def test_trama_del_controlador_se_publica_con_el_envoltorio_unico(tmp_path):
    nucleo, _, salida, _ = _nucleo(tmp_path)
    trama = Trama(
        seq=1042, tipo="PES", campos={"veh": "V02", "g": "38500", "n": "12", "meseta": "1"}
    )
    nucleo.procesar_bytes(trama.armar_linea().encode())
    assert salida.publicaciones[0].topico == "portus/evt/pesaje"
    mensaje = salida.publicaciones[0].json()
    assert mensaje["datos"] == {"veh": "V02", "peso_g": 38500, "muestras": 12, "meseta": True}
    assert nucleo.estado.contadores.tramas_validas == 1


def test_trama_con_crc_invalido_se_cuenta_como_invalida(tmp_path):
    nucleo, _, _, _ = _nucleo(tmp_path)
    nucleo.procesar_bytes(b"^1042|PES|veh=V02,g=38500,n=12,meseta=1#0000\n")
    assert nucleo.estado.contadores.tramas_invalidas == 1
    assert nucleo.estado.contadores.tramas_validas == 0


def test_salto_de_seq_genera_diagnostico_y_solicitud_syn(tmp_path):
    nucleo, puerto, salida, _ = _nucleo(tmp_path)
    nucleo.procesar_bytes(
        Trama(seq=100, tipo="EST", campos={"modo": "NORMAL"}).armar_linea().encode()
    )
    nucleo.procesar_bytes(Trama(seq=103, tipo="EST", campos={}).armar_linea().encode())
    saltos = [p for p in salida.publicaciones if p.json()["tipo"] == "enlace.salto_secuencia"]
    assert len(saltos) == 1
    assert saltos[0].json()["datos"]["seq_esperada"] == 101
    assert "|SYN|desde=101#" in puerto.recibido().decode()
    assert nucleo.estado.contadores.saltos_secuencia == 1


def test_retroceso_de_seq_no_genera_syn(tmp_path):
    nucleo, puerto, salida, _ = _nucleo(tmp_path)
    nucleo.procesar_bytes(Trama(seq=50, tipo="EST", campos={}).armar_linea().encode())
    nucleo.procesar_bytes(Trama(seq=48, tipo="EST", campos={}).armar_linea().encode())
    assert not [p for p in salida.publicaciones if p.json()["tipo"] == "enlace.salto_secuencia"]
    assert "SYN" not in puerto.recibido().decode()


def test_latido_registra_vigilante_y_persistencia(tmp_path):
    nucleo, _, _, _ = _nucleo(tmp_path)
    nucleo.procesar_bytes(
        Trama(seq=2210, tipo="EST", campos={"modo": "NORMAL"}).armar_linea().encode()
    )
    assert nucleo.vigilante.estado.value == "activo"
    assert nucleo.persistencia.ultimo_latido_ts() == MARCA_TIEMPO_FIJA


def test_comando_de_la_plataforma_se_envia_como_trama_cmd(tmp_path):
    nucleo, puerto, _, _ = _nucleo(tmp_path)
    nucleo.atender_mensaje_mqtt("portus/cmd/solicitud", _solicitud_mqtt())
    linea = puerto.recibido().decode()
    assert linea.startswith("^") and "|CMD|nombre=AbrirTalanquera#" in linea


def test_rsp_del_controlador_publica_respuesta_con_cmd_id(tmp_path):
    nucleo, _, salida, _ = _nucleo(tmp_path)
    nucleo.atender_mensaje_mqtt("portus/cmd/solicitud", _solicitud_mqtt())
    nucleo.procesar_bytes(Trama(seq=1, tipo="RSP", campos={"estado": "ACK"}).armar_linea().encode())
    respuestas = [p for p in salida.publicaciones if p.topico == "portus/cmd/respuesta"]
    assert len(respuestas) == 1
    datos = respuestas[0].json()["datos"]
    assert datos["cmd_id"] == CMD_ID
    assert datos["estado"] == "ACK"
    assert nucleo.persistencia.comando_resuelto(CMD_ID) == ("ACK", None, 1)


def test_comando_sin_respuesta_vence_con_nak_sintetico_sin_respuesta(tmp_path):
    nucleo, _, salida, reloj = _nucleo(tmp_path)
    nucleo.atender_mensaje_mqtt("portus/cmd/solicitud", _solicitud_mqtt())
    reloj.avanzar(2_000)
    vencidos = nucleo.expirar_comandos()
    assert vencidos == 1
    respuestas = [p for p in salida.publicaciones if p.topico == "portus/cmd/respuesta"]
    datos = respuestas[-1].json()["datos"]
    assert datos["estado"] == "NAK"
    assert datos["causa"] == "SIN_RESPUESTA"
    assert datos["sintetica"] is True
    assert nucleo.persistencia.comando_resuelto(CMD_ID) == ("NAK", "SIN_RESPUESTA", 1)


def test_solicitud_con_comando_desconocido_no_llega_al_serial(tmp_path):
    nucleo, puerto, salida, _ = _nucleo(tmp_path)
    nucleo.atender_mensaje_mqtt("portus/cmd/solicitud", _solicitud_mqtt(nombre="EncenderLuces"))
    assert puerto.recibido() == b""
    respuestas = [p for p in salida.publicaciones if p.topico == "portus/cmd/respuesta"]
    assert respuestas[0].json()["datos"]["causa"] == "COMANDO_DESCONOCIDO"


def test_mensaje_mqtt_mal_formado_se_descarta_sin_interrumpir(tmp_path):
    nucleo, _, salida, _ = _nucleo(tmp_path)
    nucleo.atender_mensaje_mqtt("portus/cmd/solicitud", b"no-es-json")
    nucleo.atender_mensaje_mqtt("portus/cmd/solicitud", b'{"id": 1}')
    assert salida.publicaciones == []


def test_mensaje_mqtt_no_comando_se_persiste_con_deduplicacion(tmp_path):
    nucleo, _, _, _ = _nucleo(tmp_path)
    contenido = {
        "id": "ev-1",
        "ts": MARCA_TIEMPO_FIJA,
        "origen": "servidor",
        "tipo": "turno.creado",
        "seq": None,
        "datos": {"turno": 1},
    }
    nucleo.atender_mensaje_mqtt("portus/srv/turno", json.dumps(contenido).encode())
    nucleo.atender_mensaje_mqtt("portus/srv/turno", json.dumps(contenido).encode())
    assert nucleo.persistencia.cantidad_eventos() == 1


def test_perdida_de_enlace_genera_al01_y_estado_perdido(tmp_path):
    nucleo, _, salida, reloj = _nucleo(tmp_path)
    nucleo.procesar_bytes(Trama(seq=10, tipo="EST", campos={}).armar_linea().encode())
    reloj.avanzar(20_000)
    hubo_al01 = nucleo.comprobar_vigilante()
    assert hubo_al01 is True
    alarmas = [p for p in salida.publicaciones if p.topico == "portus/srv/alarma"]
    assert alarmas[0].json()["datos"]["codigo"] == "AL01"
    enlaces = [p for p in salida.publicaciones if p.topico == "portus/srv/enlace"]
    assert enlaces[-1].json()["datos"]["enlace"] == "perdido"
    assert nucleo.comprobar_vigilante() is False


def test_recuperacion_del_enlace_publica_estado_activo_y_syn(tmp_path):
    nucleo, puerto, salida, reloj = _nucleo(tmp_path)
    nucleo.procesar_bytes(Trama(seq=10, tipo="EST", campos={}).armar_linea().encode())
    reloj.avanzar(20_000)
    nucleo.comprobar_vigilante()
    nucleo.procesar_bytes(Trama(seq=11, tipo="EST", campos={}).armar_linea().encode())
    enlaces = [p for p in salida.publicaciones if p.topico == "portus/srv/enlace"]
    assert enlaces[-1].json()["datos"]["enlace"] == "activo"
    assert "|SYN|desde=11,estado=1#" in puerto.recibido().decode()


def test_al01_retroactiva_al_arrancar_sobre_bd_con_latido_viejo(tmp_path):
    reloj_utc = RelojUtcFalso()
    nucleo, _, _, reloj = _nucleo(tmp_path, reloj_utc=reloj_utc)
    nucleo.procesar_bytes(Trama(seq=1, tipo="EST", campos={}).armar_linea().encode())
    reloj_utc.avanzar_ms(3_600_000)
    reloj.avanzar(3_600_000)
    nucleo_arranque, _, salida_arranque, _ = _nucleo(tmp_path, reloj_utc=reloj_utc)
    assert nucleo_arranque.alarma_retroactiva_si_aplica() is True
    alarmas = [p for p in salida_arranque.publicaciones if p.topico == "portus/srv/alarma"]
    assert alarmas[0].json()["datos"]["retroactiva"] is True


def test_al01_retroactiva_sin_historial_previo_no_se_genera(tmp_path):
    reloj_utc = RelojUtcFalso()
    nucleo, _, salida, _ = _nucleo(tmp_path, reloj_utc=reloj_utc)
    assert nucleo.alarma_retroactiva_si_aplica() is False
    assert salida.publicaciones == []


def test_ping_y_syn_iniciales_se_envian_al_puerto(tmp_path):
    nucleo, puerto, _, _ = _nucleo(tmp_path)
    nucleo.volcar_estado_inicial()
    nucleo.emitir_ping()
    recibido = puerto.recibido().decode()
    assert "|SYN|estado=1#" in recibido
    assert "|PING|#" in recibido
