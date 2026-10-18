"""``/cita`` multipaso y ofrecimiento de franjas (SPECS §15.2, §11.1, §11.3).

Reloj falso: 2026-09-20 08:03 en la terminal → la primera franja ofrecible
es la de 08:15 (siguiente límite de 15 min).
"""

from datetime import UTC, datetime

import pytest

from mensajeria.textos import (
    TEXTO_CONVERSACION_VENCIDA,
    TEXTO_SIN_CITABLES,
)
from pruebas.utilidades_logica import CREADO_EN
from pruebas.utilidades_mensajeria import CHAT_1, CHAT_2, crear_bot
from web.modelos.cita import OcupacionFranja, franjas_ofrecibles


@pytest.fixture()
def prueba(tmp_path):
    bot = crear_bot(tmp_path)
    bot.vincular(CHAT_1, bot.transportista_1)
    bot.vincular(CHAT_2, bot.transportista_2)
    yield bot
    bot.logica.bd.cerrar()


def _datos(respuesta) -> list[str]:
    return [boton.dato for fila in respuesta.botones for boton in fila]


# ------------------------------------------------------ ofrecimiento §11.3


def test_ofrece_las_cuatro_proximas_franjas_desde_el_siguiente_limite() -> None:
    ahora = datetime(2026, 9, 20, 14, 3, tzinfo=UTC)  # 08:03 local
    franjas = franjas_ofrecibles(ahora, {})
    assert [(f.inicio, f.fin) for f in franjas] == [
        ("08:15", "08:30"),
        ("08:30", "08:45"),
        ("08:45", "09:00"),
        ("09:00", "09:15"),
    ]


def test_no_ofrece_franjas_llenas_ni_bloqueadas() -> None:
    ahora = datetime(2026, 9, 20, 14, 3, tzinfo=UTC)
    ocupacion = {
        ("2026-09-20", "08:15"): OcupacionFranja(bloqueada=False, asignadas=2),
        ("2026-09-20", "08:30"): OcupacionFranja(bloqueada=True, asignadas=0),
        ("2026-09-20", "08:45"): OcupacionFranja(bloqueada=False, asignadas=1),
    }
    inicios = [f.inicio for f in franjas_ofrecibles(ahora, ocupacion)]
    assert inicios == ["08:45", "09:00", "09:15", "09:30"]  # §11.1 regla 5


def test_ofrecimiento_cruza_la_medianoche_local() -> None:
    ahora = datetime(2026, 9, 21, 5, 50, tzinfo=UTC)  # 23:50 del 20 en la terminal
    franjas = franjas_ofrecibles(ahora, {}, cantidad=2)
    assert [(f.fecha, f.inicio) for f in franjas] == [
        ("2026-09-21", "00:00"),
        ("2026-09-21", "00:15"),
    ]


# -------------------------------------------------------------- conversación


def test_cita_lista_solo_contenedores_propios_con_levante_y_sin_cita(prueba) -> None:
    propio = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    con_cita = prueba.manifiesto_con_levante("C02", prueba.transportista_1)
    prueba.citas.crear(con_cita, prueba.transportista_1, "2026-09-20", "09:00", CREADO_EN)
    prueba.manifiesto_con_levante("C03", prueba.transportista_2)  # ajeno
    sin_levante = prueba.manifiesto_con_levante("C04", prueba.transportista_1)
    prueba.logica.manifiestos.marcar_documental(sin_levante, "levante_solicitado")
    respuesta = prueba.escribir(CHAT_1, "/cita")
    assert _datos(respuesta) == [f"c:{propio}"]
    assert "C01" in respuesta.botones[0][0].texto


def test_cita_sin_contenedores_citables_lo_explica(prueba) -> None:
    assert prueba.escribir(CHAT_2, "/cita").texto == TEXTO_SIN_CITABLES


def test_cita_completa_confirma_contenedor_fecha_inicio_y_fin(prueba) -> None:
    manifiesto = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    prueba.escribir(CHAT_1, "/cita")
    franjas = prueba.pulsar(CHAT_1, f"c:{manifiesto}")
    assert _datos(franjas)[0] == "f:2026-09-20|08:15"
    assert "C01" in franjas.texto
    confirmacion = prueba.pulsar(CHAT_1, "f:2026-09-20|08:30").texto
    assert "C01" in confirmacion and "20/09/2026" in confirmacion
    assert "de 08:30 a 08:45" in confirmacion
    with prueba.logica.bd.candado:
        cita = prueba.logica.bd.conexion.execute(
            "SELECT manifiesto_id, transportista_id, franja_fecha, franja_inicio, estado FROM cita"
        ).fetchone()
        aviso = prueba.logica.bd.conexion.execute(
            "SELECT tipo, entregado FROM notificacion WHERE transportista_id = ?",
            (prueba.transportista_1,),
        ).fetchone()
    assert tuple(cita) == (manifiesto, prueba.transportista_1, "2026-09-20", "08:30", "programada")
    assert tuple(aviso) == ("cita_asignada", 1)  # §15.3 aviso 3 = la confirmación
    assert prueba.escribir(CHAT_1, "/cita").texto == TEXTO_SIN_CITABLES  # §11.1 regla 4


def test_franja_que_se_lleno_mientras_elegia_ofrece_otras(prueba) -> None:
    """§11.3 paso 4: la reserva vuelve a verificar la capacidad en la transacción."""
    manifiesto = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    prueba.escribir(CHAT_1, "/cita")
    assert "f:2026-09-20|08:15" in _datos(prueba.pulsar(CHAT_1, f"c:{manifiesto}"))
    for contenedor in ("C05", "C06"):  # otro transportista llena la franja entretanto
        otro = prueba.manifiesto_con_levante(contenedor, prueba.transportista_2)
        prueba.citas.reservar(otro, prueba.transportista_2, "2026-09-20", "08:15", CREADO_EN)
    respuesta = prueba.pulsar(CHAT_1, "f:2026-09-20|08:15")
    assert "se llenó" in respuesta.texto
    assert "f:2026-09-20|08:15" not in _datos(respuesta)
    with prueba.logica.bd.candado:
        ocupadas = prueba.logica.bd.conexion.execute(
            "SELECT COUNT(*) FROM cita WHERE franja_inicio = '08:15' AND estado = 'programada'"
        ).fetchone()[0]
    assert ocupadas == 2  # nunca 3 (§11.1 regla 2)


def test_boton_no_ofrecido_se_rechaza(prueba) -> None:
    prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    ajeno = prueba.manifiesto_con_levante("C03", prueba.transportista_2)
    prueba.escribir(CHAT_1, "/cita")
    assert prueba.pulsar(CHAT_1, f"c:{ajeno}").texto == TEXTO_CONVERSACION_VENCIDA
    assert prueba.pulsar(CHAT_1, "f:2026-09-20|08:15").texto == TEXTO_CONVERSACION_VENCIDA
    assert prueba.pulsar(CHAT_1, "c:1;DROP").texto == TEXTO_CONVERSACION_VENCIDA


def test_franja_no_ofrecida_se_rechaza(prueba) -> None:
    manifiesto = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    prueba.escribir(CHAT_1, "/cita")
    prueba.pulsar(CHAT_1, f"c:{manifiesto}")
    assert prueba.pulsar(CHAT_1, "f:2026-09-20|23:00").texto == TEXTO_CONVERSACION_VENCIDA


def test_otro_comando_cancela_la_conversacion(prueba) -> None:
    manifiesto = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    prueba.escribir(CHAT_1, "/cita")
    prueba.escribir(CHAT_1, "/ayuda")
    assert prueba.pulsar(CHAT_1, f"c:{manifiesto}").texto == TEXTO_CONVERSACION_VENCIDA


def test_conversacion_expira_por_inactividad(prueba) -> None:
    manifiesto = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    prueba.escribir(CHAT_1, "/cita")
    prueba.logica.reloj.avanzar_ms(11 * 60 * 1000)
    assert prueba.pulsar(CHAT_1, f"c:{manifiesto}").texto == TEXTO_CONVERSACION_VENCIDA


def test_botones_de_otro_chat_no_sirven(prueba) -> None:
    manifiesto = prueba.manifiesto_con_levante("C01", prueba.transportista_1)
    prueba.escribir(CHAT_1, "/cita")
    assert prueba.pulsar(CHAT_2, f"c:{manifiesto}").texto == TEXTO_CONVERSACION_VENCIDA


def test_reserva_rechaza_manifiesto_ajeno_aunque_llegue_directo(prueba) -> None:
    ajeno = prueba.manifiesto_con_levante("C03", prueba.transportista_2)
    reserva = prueba.citas.reservar(ajeno, prueba.transportista_1, "2026-09-20", "09:00", CREADO_EN)
    assert reserva.cita_id is None and reserva.motivo == "SIN_CARGA"
