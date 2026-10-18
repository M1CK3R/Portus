"""Consola del simulador (--interactivo): cada orden produce las tramas del controlador."""

import pytest

from herramientas.simulador_controlador import _eventos_de_job, _eventos_de_orden

JOB_DEPOSITO = {"id": "1", "tipo": "DEPOSITO", "origen": "VEH", "destino": "P1", "nivel": "1",
                "cont": "C01", "turno": "1"}  # fmt: skip
JOB_REMOCION = {"id": "2", "tipo": "REMOCION", "origen": "P3/N2", "destino": "P4/N1", "nivel": "1",
                "cont": "C02", "turno": "2"}  # fmt: skip
JOB_RETIRO = {"id": "3", "tipo": "RETIRO", "origen": "P3/N1", "destino": "VEH", "nivel": "1",
              "cont": "C03", "turno": "2"}  # fmt: skip


def test_pes_lleva_peso_bruto_con_meseta() -> None:
    eventos = _eventos_de_orden(["pes", "V01", "45000"], {})

    assert eventos == [("PES", {"veh": "V01", "g": "45000", "n": "12", "meseta": "1"})]


def test_grua_de_deposito_confirma_ocupacion_del_destino() -> None:
    tipos_y_pat = [
        (tipo, campos.get("estado")) for tipo, campos in _eventos_de_job(JOB_DEPOSITO, False)
    ]

    assert tipos_y_pat == [("GRU", None), ("PAT", "OCUPADA"), ("GRU", None)]
    assert _eventos_de_job(JOB_DEPOSITO, False)[1][1]["pos"] == "P1"


def test_grua_de_remocion_ocupa_el_destino_con_su_nivel() -> None:
    pat = _eventos_de_job(JOB_REMOCION, False)[1][1]

    assert (pat["pos"], pat["nivel"], pat["estado"]) == ("P4", "1", "OCUPADA")


def test_grua_de_retiro_libera_el_origen() -> None:
    pat = _eventos_de_job(JOB_RETIRO, False)[1][1]

    assert (pat["pos"], pat["nivel"], pat["estado"]) == ("P3", "1", "LIBRE")


def test_grua_aborto_no_emite_pat() -> None:
    eventos = _eventos_de_job(JOB_DEPOSITO, True)

    assert [campos["paso"] for _, campos in eventos] == ["IZANDO", "ABORTO"]


def test_grua_sin_job_explica_que_falta_trf() -> None:
    with pytest.raises(ValueError, match="trf"):
        _eventos_de_orden(["grua"], {})


def test_orden_desconocida_pide_ayuda() -> None:
    assert _eventos_de_orden(["bailar"], {}) is None
