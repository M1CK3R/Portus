"""Pruebas de la persistencia SQLite: deduplicación por id, telemetría y comandos (§5.7)."""

import pytest

from pruebas.utilidades_pruebas import MARCA_TIEMPO_FIJA
from puente.persistencia_sqlite import RUTA_ESQUEMA_POR_OMISION, PersistenciaSqlite


def _persistencia(tmp_path, nombre: str = "prueba.db") -> PersistenciaSqlite:
    return PersistenciaSqlite(str(tmp_path / nombre))


def test_la_ruta_de_esquema_por_omision_resuelve_a_db_esquema_sql():
    # CODESTYLE BD-2 / A-6: una sola fuente de verdad para el DDL. Antes el
    # esquema estaba copiado a mano dentro de este módulo, separado del
    # archivo real; esta prueba falla si alguien vuelve a duplicarlo.
    assert RUTA_ESQUEMA_POR_OMISION.name == "esquema.sql"
    assert RUTA_ESQUEMA_POR_OMISION.parent.name == "db"
    assert RUTA_ESQUEMA_POR_OMISION.is_file()


def test_arranca_leyendo_de_verdad_el_esquema_del_repositorio(tmp_path):
    # Sin pasar ruta_esquema, debe usar RUTA_ESQUEMA_POR_OMISION y crear las
    # tablas reales de db/esquema.sql, no una copia interna del DDL.
    persistencia = PersistenciaSqlite(str(tmp_path / "esquema_real.db"))
    assert persistencia.cantidad_eventos() == 0
    assert persistencia.cantidad_telemetria() == 0


def test_esquema_inexistente_falla_con_mensaje_explicito(tmp_path):
    ruta_esquema_inexistente = tmp_path / "no_existe.sql"
    with pytest.raises(RuntimeError, match="no se encontró el esquema SQL"):
        PersistenciaSqlite(str(tmp_path / "otra.db"), ruta_esquema=ruta_esquema_inexistente)


def test_evento_se_guarda_y_el_duplicado_por_id_no_crea_fila(tmp_path):
    persistencia = _persistencia(tmp_path)
    insertado = persistencia.guardar_evento(
        "id-1",
        MARCA_TIEMPO_FIJA,
        "controlador",
        "pesaje.medicion",
        1042,
        {"peso_g": 38500},
        "portus/evt/pesaje",
    )
    duplicado = persistencia.guardar_evento(
        "id-1",
        MARCA_TIEMPO_FIJA,
        "controlador",
        "pesaje.medicion",
        1042,
        {"peso_g": 38500},
        "portus/evt/pesaje",
    )
    assert insertado is True
    assert duplicado is False
    assert persistencia.cantidad_eventos() == 1


def test_telemetria_deduplica_por_identificador(tmp_path):
    persistencia = _persistencia(tmp_path)
    persistencia.guardar_telemetria("t-1", MARCA_TIEMPO_FIJA, "latido", {"modo": "NORMAL"})
    persistencia.guardar_telemetria("t-1", MARCA_TIEMPO_FIJA, "latido", {"modo": "NORMAL"})
    assert persistencia.cantidad_telemetria() == 1


def test_comando_se_registra_y_actualiza_su_estado(tmp_path):
    persistencia = _persistencia(tmp_path)
    persistencia.registrar_comando_solicitado(
        "cmd-1", MARCA_TIEMPO_FIJA, "terminal", "AbrirTalanquera", {}, 57
    )
    persistencia.registrar_comando_resuelto("cmd-1", "NAK", "SIN_RESPUESTA", False)
    assert persistencia.comando_resuelto("cmd-1") == ("NAK", "SIN_RESPUESTA", 57)


def test_ultimo_latido_se_guarda_para_la_al01_retroactiva(tmp_path):
    persistencia = _persistencia(tmp_path)
    assert persistencia.ultimo_latido_ts() is None
    persistencia.registrar_latido(MARCA_TIEMPO_FIJA)
    assert persistencia.ultimo_latido_ts() == MARCA_TIEMPO_FIJA


def test_estado_de_enlace_se_actualiza(tmp_path):
    persistencia = _persistencia(tmp_path)
    persistencia.actualizar_estado_enlace("perdido", MARCA_TIEMPO_FIJA, MARCA_TIEMPO_FIJA)
    assert persistencia.estado_enlace_guardado() == ("perdido", MARCA_TIEMPO_FIJA)
