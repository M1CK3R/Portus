"""Las 9 notificaciones: generación, entrega, recordatorio y frontera MQTT/Telegram.

SPECS §15.3 (contenido mínimo y solo al propietario), §15.4 (cola, 429,
reintentos, sin internet, idempotencia) y §11.5 (recordatorio 1 h antes).
"""

import asyncio
import json
from datetime import timedelta

import pytest
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from mensajeria.adaptador_telegram import CanalTelegram
from mensajeria.configuracion import ConfiguracionMensajeria
from mensajeria.despachador import (
    MAX_REINTENTOS_PERMANENTES,
    DespachadorAvisos,
    ResultadoEntrega,
)
from mensajeria.escucha_mqtt import EscuchaAvisos
from mensajeria.formato import LARGO_MAXIMO_MENSAJE
from mensajeria.modelos import (
    ErrorLimiteCanal,
    ErrorPermanenteCanal,
    ErrorRedCanal,
)
from mensajeria.recordatorios import PlanificadorRecordatorios
from mensajeria.redactor import _REDACTORES, redactar
from pruebas.utilidades_logica import CREADO_EN
from pruebas.utilidades_mensajeria import CHAT_1, CanalFalso, TiempoFalso, crear_bot
from web.modelos.notificacion import TipoNotificacion
from web.repositorios.repositorio_declaraciones import RepositorioDeclaraciones
from web.repositorios.repositorio_inventario import RepositorioInventario
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.repositorios.repositorio_vehiculos import RepositorioVehiculos
from web.servicios.servicio_levantes import ServicioLevantes


@pytest.fixture()
def prueba(tmp_path):
    bot = crear_bot(tmp_path)
    yield bot
    bot.logica.bd.cerrar()


def _despachador(prueba, canal: CanalFalso, tiempo: TiempoFalso) -> DespachadorAvisos:
    return DespachadorAvisos(
        prueba.notificaciones,
        prueba.vinculos,
        canal,
        prueba.logica.reloj,
        reloj_monotonico=tiempo.reloj,
        dormir=tiempo.dormir,
    )


def _aviso(prueba, transportista_id: int, contenedor: str = "C01") -> int:
    return prueba.notificaciones.crear(
        transportista_id,
        TipoNotificacion.LEVANTE_RETENIDO.value,
        {"contenedor": contenedor, "motivo": "documentos incompletos"},
        "2026-09-20T14:03:22.418Z",
    )


# ------------------------------------------------ generación en la web §15.3


def _levantes(prueba) -> ServicioLevantes:
    bd = prueba.logica.bd
    return ServicioLevantes(
        prueba.logica.levantes,
        prueba.logica.manifiestos,
        RepositorioDeclaraciones(bd),
        RepositorioInventario(bd),
        RepositorioUsuarios(bd),
        prueba.logica.nucleo.notificador,
        prueba.logica.reloj,
    )


def test_otorgar_levante_rojo_avisa_al_transportista_con_canal_y_verificacion(prueba) -> None:
    manifiesto = prueba.manifiesto("C01", prueba.transportista_1)
    levante = prueba.logica.levantes.crear(manifiesto, "solicitada")
    assert _levantes(prueba).otorgar(levante, "rojo", prueba.naviera) == (True, "")
    publicado = prueba.logica.publicador.datos_de("notificacion.levante_otorgado")[-1]
    assert publicado["contenedor"] == "C01" and publicado["canal"] == "rojo"
    assert publicado["transportista"] == prueba.transportista_1
    fila = prueba.notificaciones.buscar_por_id(publicado["notificacion"])
    texto = redactar(fila.tipo, fila.payload)
    assert "C01" in texto and "rojo" in texto and "verificación" in texto  # aviso 1


def test_retener_levante_avisa_con_el_motivo(prueba) -> None:
    manifiesto = prueba.manifiesto("C02", prueba.transportista_2, "RETIRO")
    levante = prueba.logica.levantes.crear(manifiesto, "solicitada")
    _levantes(prueba).retener(levante, "Falta factura <original>", prueba.naviera)
    publicado = prueba.logica.publicador.datos_de("notificacion.levante_retenido")[-1]
    texto = redactar("levante_retenido", publicado)
    assert "C02" in texto and "Falta factura <original>" in texto  # aviso 2, texto plano


def test_cancelar_y_reprogramar_cita_avisan_con_contenedor_y_ventana(prueba) -> None:
    manifiesto = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    cita = prueba.citas.crear(manifiesto, prueba.transportista_1, "2026-09-20", "09:00", CREADO_EN)
    citas_svc = prueba.logica.nucleo.citas_svc
    assert citas_svc.reprogramar(cita, "2026-09-20", "10:15") == (True, "")
    reprogramada = prueba.logica.publicador.datos_de("notificacion.cita_reprogramada")[-1]
    assert (reprogramada["contenedor"], reprogramada["inicio"], reprogramada["fin"]) == (
        "C01",
        "10:15",
        "10:30",
    )
    assert citas_svc.cancelar(cita)
    cancelada = prueba.logica.publicador.datos_de("notificacion.cita_cancelada")[-1]
    assert cancelada["contenedor"] == "C01" and cancelada["transportista"] == prueba.transportista_1


def test_agenda_muestra_una_sola_vez_la_cita_de_un_transportista_con_dos_vehiculos(
    prueba,
) -> None:
    RepositorioVehiculos(prueba.logica.bd).crear("V02", prueba.transportista_1, 900)
    manifiesto = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    prueba.citas.crear(manifiesto, prueba.transportista_1, "2026-09-20", "09:00", CREADO_EN)
    franja = next(f for f in prueba.citas.agenda_de_fecha("2026-09-20") if f.inicio == "09:00")
    assert len(franja.citas) == 1 and franja.citas[0].vehiculo == "V01, V02"


def test_todo_aviso_publicado_lleva_el_id_de_su_fila(prueba) -> None:
    manifiesto = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    cita = prueba.citas.crear(manifiesto, prueba.transportista_1, "2026-09-20", "09:00", CREADO_EN)
    prueba.logica.nucleo.citas_svc.cancelar(cita)
    for _, tipo, datos in prueba.logica.publicador.publicados:
        if tipo.startswith("notificacion."):
            fila = prueba.notificaciones.buscar_por_id(datos["notificacion"])
            assert fila is not None and f"notificacion.{fila.tipo}" == tipo


def test_cada_tipo_de_notificacion_tiene_su_redactor() -> None:
    assert set(_REDACTORES) == set(TipoNotificacion)


def test_aviso_de_retencion_de_peso_muestra_declarado_medido_y_diferencia() -> None:
    texto = redactar(
        "vehiculo_retenido",
        {
            "vehiculo": "V01",
            "contenedor": "C01",
            "causa": "RT01",
            "peso_declarado_g": 38_500,
            "peso_medido_g": 42_000,
            "diferencia_g": 3_500,
            "diferencia_pct": 9.09,
        },
    )
    assert "V01" in texto and "Discrepancia de peso al ingreso (RT01)" in texto
    assert "38 500 g" in texto and "42 000 g" in texto and "3 500 g" in texto


def test_turno_completado_indica_tipo_y_tiempo_total() -> None:
    texto = redactar(
        "turno_completado",
        {"vehiculo": "V01", "contenedor": "C01", "tipo_op": "RETIRO", "tiempo_total_s": 3_720},
    )
    assert "Retiro" in texto and "1 h 02 min" in texto  # aviso 8


def test_mensaje_largo_se_recorta_al_limite_de_telegram() -> None:
    texto = redactar("levante_retenido", {"contenedor": "C01", "motivo": "x" * 5000})
    assert len(texto) == LARGO_MAXIMO_MENSAJE


# ------------------------------------------------------ cola de envío §15.4


def test_entrega_al_chat_del_propietario_y_marca_entregado(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    aviso = _aviso(prueba, prueba.transportista_1)
    canal, tiempo = CanalFalso(), TiempoFalso()
    resultado = asyncio.run(_despachador(prueba, canal, tiempo).entregar(aviso))
    assert resultado is ResultadoEntrega.ENTREGADA
    assert canal.enviados[0][0] == CHAT_1 and "documentos incompletos" in canal.enviados[0][1]
    assert prueba.notificaciones.buscar_por_id(aviso).entregado


def test_aviso_ya_entregado_no_se_reenvia(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    aviso = _aviso(prueba, prueba.transportista_1)
    canal, tiempo = CanalFalso(), TiempoFalso()
    despachador = _despachador(prueba, canal, tiempo)
    asyncio.run(despachador.entregar(aviso))
    assert asyncio.run(despachador.entregar(aviso)) is ResultadoEntrega.OMITIDA  # P-4
    assert len(canal.enviados) == 1


def test_aviso_de_transportista_sin_vinculo_queda_pendiente(prueba) -> None:
    aviso = _aviso(prueba, prueba.transportista_2)
    canal = CanalFalso()
    resultado = asyncio.run(_despachador(prueba, canal, TiempoFalso()).entregar(aviso))
    assert resultado is ResultadoEntrega.OMITIDA and canal.enviados == []
    assert not prueba.notificaciones.buscar_por_id(aviso).entregado


def test_sin_internet_queda_pendiente_sin_gastar_reintentos_y_el_barrido_lo_recupera(
    prueba,
) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    aviso = _aviso(prueba, prueba.transportista_1)
    canal = CanalFalso(errores=[ErrorRedCanal("sin conexión")] * (MAX_REINTENTOS_PERMANENTES + 2))
    despachador = _despachador(prueba, canal, TiempoFalso())
    for _ in range(MAX_REINTENTOS_PERMANENTES + 2):
        assert asyncio.run(despachador.entregar(aviso)) is ResultadoEntrega.PENDIENTE_RED
    assert prueba.notificaciones.por_entregar(MAX_REINTENTOS_PERMANENTES, 50) == [aviso]
    assert asyncio.run(despachador.entregar(aviso)) is ResultadoEntrega.ENTREGADA
    assert prueba.notificaciones.por_entregar(MAX_REINTENTOS_PERMANENTES, 50) == []


def test_respeta_retry_after_y_reintenta_una_vez(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    aviso = _aviso(prueba, prueba.transportista_1)
    canal, tiempo = CanalFalso(errores=[ErrorLimiteCanal(7)]), TiempoFalso()
    resultado = asyncio.run(_despachador(prueba, canal, tiempo).entregar(aviso))
    assert resultado is ResultadoEntrega.ENTREGADA
    assert 7 in tiempo.esperas and len(canal.enviados) == 1


def test_rechazo_permanente_se_abandona_tras_tres_reintentos(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    aviso = _aviso(prueba, prueba.transportista_1)
    canal = CanalFalso(errores=[ErrorPermanenteCanal("bot bloqueado")] * 3)
    despachador = _despachador(prueba, canal, TiempoFalso())
    for _ in range(MAX_REINTENTOS_PERMANENTES):
        assert prueba.notificaciones.por_entregar(MAX_REINTENTOS_PERMANENTES, 50) == [aviso]
        assert asyncio.run(despachador.entregar(aviso)) is ResultadoEntrega.RECHAZADA
    assert prueba.notificaciones.por_entregar(MAX_REINTENTOS_PERMANENTES, 50) == []


def test_espacia_los_envios_al_mismo_chat_un_segundo(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    avisos = [_aviso(prueba, prueba.transportista_1, f"C0{n}") for n in range(1, 4)]
    canal, tiempo = CanalFalso(), TiempoFalso()
    despachador = _despachador(prueba, canal, tiempo)
    for aviso in avisos:
        asyncio.run(despachador.entregar(aviso))
    assert tiempo.esperas == [1.0, 1.0] and len(canal.enviados) == 3


def test_barrido_no_envia_avisos_anteriores_al_vinculo(prueba) -> None:
    viejo = _aviso(prueba, prueba.transportista_1)
    prueba.logica.reloj.avanzar_ms(60_000)
    prueba.vincular(CHAT_1, prueba.transportista_1)
    nuevo = prueba.notificaciones.crear(
        prueba.transportista_1,
        "levante_otorgado",
        {"contenedor": "C01", "canal": "verde"},
        "2026-09-20T14:05:00.000Z",
    )
    assert prueba.notificaciones.por_entregar(MAX_REINTENTOS_PERMANENTES, 50) == [nuevo]
    assert viejo != nuevo


def test_trabajador_de_la_cola_entrega_lo_encolado_una_vez(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    aviso = _aviso(prueba, prueba.transportista_1)
    canal, tiempo = CanalFalso(), TiempoFalso()

    async def escenario() -> None:
        despachador = _despachador(prueba, canal, tiempo)
        despachador.encolar(aviso)
        despachador.encolar(aviso)  # duplicado por QoS 1 antes de salir
        trabajador = asyncio.create_task(despachador.ejecutar())
        await asyncio.wait_for(despachador._cola.join(), timeout=5)
        trabajador.cancel()

    asyncio.run(escenario())
    assert len(canal.enviados) == 1


# ----------------------------------------------------------- escucha MQTT


def _envoltorio(id_mensaje: str, tipo: str, datos: dict) -> bytes:
    return json.dumps(
        {
            "id": id_mensaje,
            "ts": "t",
            "origen": "servidor",
            "tipo": tipo,
            "seq": None,
            "datos": datos,
        }
    ).encode("utf-8")


def test_escucha_entrega_una_vez_el_aviso_repetido_por_el_broker() -> None:
    recibidos: list[int] = []
    escucha = EscuchaAvisos("127.0.0.1", 1883, "portus-msg", "x", recibidos.append)
    carga = _envoltorio("m-1", "notificacion.turno_completado", {"notificacion": 7})
    assert escucha.atender(carga) and not escucha.atender(carga)
    assert recibidos == [7]


@pytest.mark.parametrize(
    "carga",
    [
        b"no es json",
        b"[1, 2]",
        _envoltorio("m-2", "turno.cambio", {"turno": 1}),
        _envoltorio("m-3", "notificacion.x", {"notificacion": "7"}),
        _envoltorio("m-4", "notificacion.x", {"notificacion": True}),
    ],
)
def test_escucha_descarta_mensajes_que_no_son_avisos(carga) -> None:
    recibidos: list[int] = []
    escucha = EscuchaAvisos("127.0.0.1", 1883, "portus-msg", "x", recibidos.append)
    assert not escucha.atender(carga) and recibidos == []


# --------------------------------------------------------- recordatorio §11.5


def test_recordatorio_sale_una_hora_antes_y_una_sola_vez(prueba) -> None:
    manifiesto = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    prueba.citas.crear(manifiesto, prueba.transportista_1, "2026-09-20", "09:15", CREADO_EN)
    planificador = PlanificadorRecordatorios(
        prueba.citas, prueba.notificaciones, prueba.logica.reloj
    )
    assert planificador.revisar() == []  # 08:03: faltan 72 min
    prueba.logica.reloj.avanzar_ms(int(timedelta(minutes=12).total_seconds() * 1000))
    creadas = planificador.revisar()  # 08:15: falta 1 h
    assert len(creadas) == 1 and planificador.revisar() == []
    fila = prueba.notificaciones.buscar_por_id(creadas[0])
    texto = redactar(fila.tipo, fila.payload)
    assert "C01" in texto and "de 09:15 a 09:30" in texto  # aviso 4


def test_reprogramar_habilita_el_recordatorio_de_la_ventana_nueva(prueba) -> None:
    manifiesto = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    cita = prueba.citas.crear(manifiesto, prueba.transportista_1, "2026-09-20", "08:30", CREADO_EN)
    planificador = PlanificadorRecordatorios(
        prueba.citas, prueba.notificaciones, prueba.logica.reloj
    )
    assert len(planificador.revisar()) == 1
    prueba.logica.nucleo.citas_svc.reprogramar(cita, "2026-09-20", "08:45")
    assert len(planificador.revisar()) == 1


def test_no_recuerda_una_cita_cuya_franja_ya_empezo(prueba) -> None:
    manifiesto = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    prueba.citas.crear(manifiesto, prueba.transportista_1, "2026-09-20", "08:00", CREADO_EN)
    planificador = PlanificadorRecordatorios(
        prueba.citas, prueba.notificaciones, prueba.logica.reloj
    )
    assert planificador.revisar() == []


# -------------------------------------------------------- frontera Telegram


class _BotQueFalla:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def send_message(self, chat_id: int, text: str) -> None:
        raise self.error


class _AplicacionFalsa:
    def __init__(self, error: Exception) -> None:
        self.bot = _BotQueFalla(error)


@pytest.mark.parametrize(
    ("error", "esperado"),
    [
        (RetryAfter(12), ErrorLimiteCanal),
        (Forbidden("bot was blocked by the user"), ErrorPermanenteCanal),
        (BadRequest("chat not found"), ErrorPermanenteCanal),
        (TimedOut(), ErrorRedCanal),
        (NetworkError("sin ruta"), ErrorRedCanal),
    ],
)
def test_canal_telegram_traduce_los_errores_de_la_bot_api(error, esperado, monkeypatch) -> None:
    monkeypatch.setenv("PTB_TIMEDELTA", "1")  # como en portus-msg: retry_after en timedelta
    canal = CanalTelegram(_AplicacionFalsa(error))
    with pytest.raises(esperado):
        asyncio.run(canal.enviar(CHAT_1, "hola"))


def test_configuracion_exige_token_y_no_lo_muestra() -> None:
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        ConfiguracionMensajeria.desde_env("MQTT_HOST=127.0.0.1\n")
    configuracion = ConfiguracionMensajeria.desde_env(
        "TELEGRAM_BOT_TOKEN=123:secreto\nMSG_MQTT_CONTRASENA=clave\n"
    )
    assert configuracion.token_bot == "123:secreto"
    assert "secreto" not in repr(configuracion) and "clave" not in repr(configuracion)
    assert configuracion.mqtt_usuario == "portus-msg"
