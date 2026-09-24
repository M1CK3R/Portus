"""Bot de Telegram: vinculación y los 7 comandos (SPECS §15.1, §15.2; ROADMAP Etapa 10).

El reloj falso marca 2026-09-20 14:03:22 UTC = 08:03 en la terminal (UTC-6).
"""

from datetime import timedelta

import pytest

from mensajeria.textos import (
    COMANDOS,
    TEXTO_CODIGO_INVALIDO,
    TEXTO_DEMASIADOS_INTENTOS,
    TEXTO_NO_RECONOCIDO,
    TEXTO_SIN_CARGA,
    TEXTO_SIN_TURNOS,
    texto_sin_vincular,
)
from pruebas.utilidades_logica import CREADO_EN, enviar
from pruebas.utilidades_mensajeria import CHAT_1, CHAT_2, NOMBRE_TERMINAL, crear_bot
from web.repositorios.repositorio_usuarios import RepositorioUsuarios


@pytest.fixture()
def prueba(tmp_path):
    bot = crear_bot(tmp_path)
    yield bot
    bot.logica.bd.cerrar()


# ------------------------------------------------------------ vinculación §15.1


@pytest.mark.parametrize(
    "texto", ["/inicio", "/start", "/cita", "/estado C01", "/misturnos", "/ayuda", "hola", "/xyz"]
)
def test_cuenta_no_vinculada_recibe_siempre_la_misma_respuesta(prueba, texto) -> None:
    respuesta = prueba.escribir(CHAT_1, texto)
    assert respuesta.texto == texto_sin_vincular(NOMBRE_TERMINAL)  # §15.1 regla 5
    assert respuesta.botones == ()


def test_vincular_con_codigo_valido_confirma_con_el_nombre_del_transportista(prueba) -> None:
    respuesta = prueba.vincular(CHAT_1, prueba.transportista_1)
    assert "Transportes Uno" in respuesta.texto
    assert prueba.vinculos.transportista_de_chat(CHAT_1) == prueba.transportista_1
    assert prueba.transportista_1 in prueba.vinculos.vinculados()  # panel de §14.5


def test_vincular_acepta_minusculas_y_espacios(prueba) -> None:
    codigo = prueba.vinculacion.generar(prueba.transportista_1)
    respuesta = prueba.escribir(CHAT_1, f"/vincular   {codigo.codigo.lower()} ")
    assert "Transportes Uno" in respuesta.texto


def test_codigo_de_un_solo_uso_no_vincula_un_segundo_chat(prueba) -> None:
    codigo = prueba.vinculacion.generar(prueba.transportista_1)
    prueba.escribir(CHAT_1, f"/vincular {codigo.codigo}")
    respuesta = prueba.escribir(CHAT_2, f"/vincular {codigo.codigo}")
    assert respuesta.texto == TEXTO_CODIGO_INVALIDO
    assert prueba.vinculos.transportista_de_chat(CHAT_2) is None


def test_codigo_vencido_a_los_60_minutos_se_rechaza(prueba) -> None:
    codigo = prueba.vinculacion.generar(prueba.transportista_1)
    prueba.logica.reloj.avanzar_ms(61 * 60 * 1000)
    assert prueba.escribir(CHAT_1, f"/vincular {codigo.codigo}").texto == TEXTO_CODIGO_INVALIDO


def test_start_con_codigo_vincula_como_el_enlace_de_telegram(prueba) -> None:
    codigo = prueba.vinculacion.generar(prueba.transportista_2)
    respuesta = prueba.escribir(CHAT_2, f"/start {codigo.codigo}")
    assert "Transportes Dos" in respuesta.texto


def test_revincular_el_chat_con_otro_codigo_reemplaza_el_vinculo(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    prueba.vincular(CHAT_1, prueba.transportista_2)
    assert prueba.vinculos.transportista_de_chat(CHAT_1) == prueba.transportista_2
    assert prueba.vinculos.chat_de_transportista(prueba.transportista_1) is None


def test_limita_los_intentos_de_vinculacion_por_chat(prueba) -> None:
    for _ in range(5):
        assert prueba.escribir(CHAT_1, "/vincular ZZZZZZ").texto == TEXTO_CODIGO_INVALIDO
    codigo = prueba.vinculacion.generar(prueba.transportista_1)
    assert prueba.escribir(CHAT_1, f"/vincular {codigo.codigo}").texto == TEXTO_DEMASIADOS_INTENTOS
    prueba.logica.reloj.avanzar_ms(16 * 60 * 1000)
    assert "Transportes Uno" in prueba.escribir(CHAT_1, f"/vincular {codigo.codigo}").texto


# ------------------------------------------------------------- comandos §15.2


def test_inicio_saluda_con_nombre_de_terminal_y_los_siete_comandos(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    for texto in ("/inicio", "/start"):
        respuesta = prueba.escribir(CHAT_1, texto).texto
        assert NOMBRE_TERMINAL in respuesta and "Transportes Uno" in respuesta
        assert all(f"/{nombre} — {descripcion}" in respuesta for nombre, descripcion in COMANDOS)


def test_ayuda_repite_la_lista_completa(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    respuesta = prueba.escribir(CHAT_1, "/ayuda").texto
    assert len(COMANDOS) == 7
    assert all(f"/{nombre}" in respuesta for nombre, _ in COMANDOS)


@pytest.mark.parametrize("texto", ["hola", "/comprar", "", "/ESTADOX"])
def test_texto_que_no_es_comando_recibe_no_reconocido_con_ayuda(prueba, texto) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    respuesta = prueba.escribir(CHAT_1, texto)
    assert respuesta.texto == TEXTO_NO_RECONOCIDO and "/ayuda" in respuesta.texto


def test_comando_con_mencion_del_bot_se_atiende(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    assert "/misturnos" in prueba.escribir(CHAT_1, "/ayuda@PortusBot").texto


def test_estado_de_contenedor_propio_en_patio(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    prueba.manifiesto_con_levante("C01", prueba.transportista_1, canal="rojo")
    with prueba.logica.bd.candado:
        prueba.logica.bd.conexion.execute(
            "INSERT INTO inventario (contenedor_id, posicion, nivel, ingreso_en) "
            "VALUES ('C01', 'P1', 1, '2026-09-20T12:00:00.000Z')"
        )
        prueba.logica.bd.conexion.commit()
    respuesta = prueba.escribir(CHAT_1, "/estado c01").texto
    assert "Contenedor C01" in respuesta
    assert "en el patio" in respuesta
    assert "posición P1, nivel 1" in respuesta
    assert "2 h 03 min" in respuesta  # 12:00 → 14:03 UTC (§15.2: h y min)
    assert "Levante otorgado" in respuesta
    assert "Canal: rojo" in respuesta


def test_estado_de_contenedor_ajeno_o_inexistente_no_revela_nada(prueba) -> None:
    """§15.2: se demuestra con los dos transportistas; ajeno e inexistente son iguales."""
    prueba.vincular(CHAT_1, prueba.transportista_1)
    prueba.vincular(CHAT_2, prueba.transportista_2)
    prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    assert prueba.escribir(CHAT_2, "/estado C01").texto == TEXTO_SIN_CARGA
    assert prueba.escribir(CHAT_2, "/estado C99").texto == TEXTO_SIN_CARGA
    assert prueba.escribir(CHAT_2, "/estado ' OR 1=1 --").texto == TEXTO_SIN_CARGA
    assert "Contenedor C01" in prueba.escribir(CHAT_1, "/estado C01").texto


def test_estado_deja_de_mostrar_un_contenedor_que_paso_a_otro_transportista(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    anterior = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    prueba.logica.manifiestos.marcar_operativo(anterior, "completado")
    prueba.manifiesto_con_levante("C01", prueba.transportista_2)
    assert prueba.escribir(CHAT_1, "/estado C01").texto == TEXTO_SIN_CARGA


def test_misturnos_lista_el_turno_activo_con_su_estacion(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    prueba.vincular(CHAT_2, prueba.transportista_2)
    manifiesto = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    prueba.citas.crear(manifiesto, prueba.transportista_1, "2026-09-20", "08:00", CREADO_EN)
    enviar(prueba.logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    respuesta = prueba.escribir(CHAT_1, "/misturnos").texto
    assert "Vehículo: V01" in respuesta and "Contenedor: C01" in respuesta
    assert "Depósito" in respuesta
    assert "Estado: EnGarita" in respuesta and "Estación: Garita" in respuesta
    assert prueba.escribir(CHAT_2, "/misturnos").texto == TEXTO_SIN_TURNOS  # aislamiento


def test_miscitas_muestra_contenedor_ventana_y_estado(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    prueba.vincular(CHAT_2, prueba.transportista_2)
    manifiesto = prueba.manifiesto_con_levante("C02", prueba.transportista_1)
    prueba.citas.crear(manifiesto, prueba.transportista_1, "2026-09-20", "10:15", CREADO_EN)
    respuesta = prueba.escribir(CHAT_1, "/miscitas").texto
    assert "Contenedor C02" in respuesta
    assert "20/09/2026, de 10:15 a 10:30" in respuesta and "hasta las 10:35" in respuesta
    assert "Estado: programada" in respuesta
    assert "C02" not in prueba.escribir(CHAT_2, "/miscitas").texto


def test_transportista_desactivado_vuelve_a_la_respuesta_de_vinculacion(prueba) -> None:
    prueba.vincular(CHAT_1, prueba.transportista_1)
    RepositorioUsuarios(prueba.logica.bd).cambiar_activo("transportista01", False)
    assert prueba.escribir(CHAT_1, "/inicio").texto == texto_sin_vincular(NOMBRE_TERMINAL)


def test_la_respuesta_de_intentos_se_libera_tras_la_ventana(prueba) -> None:
    for _ in range(6):
        prueba.escribir(CHAT_2, "/vincular AAAAAA")
    prueba.logica.reloj.avanzar_ms(int(timedelta(minutes=15).total_seconds() * 1000) + 1)
    assert prueba.escribir(CHAT_2, "/vincular AAAAAA").texto == TEXTO_CODIGO_INVALIDO
