"""Pruebas del CRC y de los ejemplos literales del SPECS §4.2 (CODESTYLE T-4)."""

import pytest

from puente.protocolo import (
    MAX_LONGITUD_TRAMA_BYTES,
    MIN_LONGITUD_TRAMA_BYTES,
    Trama,
    calcular_crc16,
    parsear_linea,
)

VECTOR_ESTANDAR = b"123456789"
VECTOR_ESPERADO = 0x29B1

EJEMPLOS_SPECS = [
    "^1042|PES|veh=V02,g=38500,n=12,meseta=1#58B2\n",
    "^2210|EST|modo=NORMAL,grua=REPOSO,link=1#A60E\n",
    "^57|CMD|nombre=AbrirTalanquera#9F98\n",
    "^57|RSP|estado=ACK#C4D8\n",
    "^58|RSP|estado=NAK,causa=VEH_BAJO_TALANQUERA#3B92\n",
]


def test_vector_estandar_del_crc_da_29b1():
    assert calcular_crc16(VECTOR_ESTANDAR) == VECTOR_ESPERADO


@pytest.mark.parametrize("linea", EJEMPLOS_SPECS)
def test_ejemplos_de_trama_del_specs_se_parsean_con_crc_valido(linea):
    trama = parsear_linea(linea)
    assert trama.armar_linea() == linea


def test_trama_pesaje_se_serializa_igual_que_el_specs():
    trama = Trama(
        seq=1042, tipo="PES", campos={"veh": "V02", "g": "38500", "n": "12", "meseta": "1"}
    )
    assert trama.armar_linea() == EJEMPLOS_SPECS[0]


def test_trama_comando_se_serializa_igual_que_el_specs():
    trama = Trama(seq=57, tipo="CMD", campos={"nombre": "AbrirTalanquera"})
    assert trama.armar_linea() == EJEMPLOS_SPECS[2]


def test_trama_nak_con_causa_se_serializa_igual_que_el_specs():
    trama = Trama(seq=58, tipo="RSP", campos={"estado": "NAK", "causa": "VEH_BAJO_TALANQUERA"})
    assert trama.armar_linea() == EJEMPLOS_SPECS[4]


def test_limites_de_longitud_de_trama_estan_definidos():
    assert MIN_LONGITUD_TRAMA_BYTES == 13
    assert MAX_LONGITUD_TRAMA_BYTES == 256
