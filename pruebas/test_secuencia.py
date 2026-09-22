"""Pruebas del rastreador de secuencia del controlador y del emisor del servidor."""

import pytest

from puente.protocolo import TIPO_CMD, ContadorSecuenciaServidor
from puente.secuencia import (
    ClaseSecuencia,
    EmisorTramasServidor,
    RastreadorSecuencia,
)


def test_primer_seq_recibido_se_toma_como_base():
    rastreador = RastreadorSecuencia()
    evento = rastreador.registrar(1042)
    assert evento.clase is ClaseSecuencia.NUEVO


def test_seq_consecutiva_es_nueva():
    rastreador = RastreadorSecuencia()
    rastreador.registrar(1042)
    assert rastreador.registrar(1043).clase is ClaseSecuencia.NUEVO
    assert rastreador.registrar(1044).clase is ClaseSecuencia.NUEVO


def test_salto_de_seq_reporta_cantidad_de_faltantes():
    rastreador = RastreadorSecuencia()
    rastreador.registrar(1042)
    evento = rastreador.registrar(1045)
    assert evento.clase is ClaseSecuencia.SALTO
    assert evento.faltantes == 2
    assert evento.seq_previa == 1042


def test_seq_repetida_se_detecta_como_duplicado():
    rastreador = RastreadorSecuencia()
    rastreador.registrar(1042)
    assert rastreador.registrar(1042).clase is ClaseSecuencia.DUPLICADO


def test_seq_anterior_se_detecta_como_atrasado():
    rastreador = RastreadorSecuencia()
    rastreador.registrar(1045)
    assert rastreador.registrar(1042).clase is ClaseSecuencia.ATRASADO


def test_envoltura_de_secuencia_de_32_bits_se_trata_como_nueva():
    rastreador = RastreadorSecuencia()
    rastreador.registrar(0xFFFFFFFF)
    assert rastreador.registrar(0).clase is ClaseSecuencia.NUEVO


def test_emisor_asigna_secuencias_crecientes_a_los_comandos():
    emisor = EmisorTramasServidor(ContadorSecuenciaServidor(seq_inicial=100))
    trama_uno = emisor.armar_cmd("AbrirTalanquera", {})
    trama_dos = emisor.armar_cmd("CerrarTalanquera", {})
    assert trama_uno.seq == 101
    assert trama_dos.seq == trama_uno.seq + 1
    assert trama_uno.tipo == TIPO_CMD


def test_emisor_armar_syn_exige_desde_o_estado():
    emisor = EmisorTramasServidor(ContadorSecuenciaServidor(seq_inicial=0))
    with pytest.raises(ValueError):
        emisor.armar_syn()
    trama = emisor.armar_syn(desde=43, volcar_estado=True)
    assert trama.campos == {"desde": "43", "estado": "1"}


def test_contador_con_base_fija_empezaria_en_el_valor_fijo():
    contador = ContadorSecuenciaServidor(seq_inicial=41)
    assert contador.siguiente() == 42
