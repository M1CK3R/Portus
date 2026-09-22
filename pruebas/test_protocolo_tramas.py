"""Pruebas del formato de trama: delimitación, escape, validación y resincronización."""

import pytest

from puente.protocolo import (
    AnalizadorTramas,
    ErrorProtocolo,
    Trama,
    TramaDescartada,
    calcular_crc16,
    desescapar,
    escapar,
    parsear_linea,
)


def test_ida_y_vuelta_de_campos_escaped_preserva_el_valor():
    valor_con_reservados = "A,B^C|D#E%F"
    trama = Trama(seq=7, tipo="GAR", campos={"causa": valor_con_reservados})
    linea = trama.armar_linea()
    trama_leida = parsear_linea(linea)
    assert trama_leida.campos["causa"] == valor_con_reservados


def test_escape_sustituye_todos_los_reservados():
    assert escapar("^|#,\n\r%") == "%5E%7C%23%2C%0A%0D%25"


def test_desescape_invalido_lanza_error_de_protocolo():
    with pytest.raises(ErrorProtocolo):
        desescapar("valor%GG")


def test_trama_con_crc_alterado_se_rechaza():
    linea = "^57|CMD|nombre=AbrirTalanquera#9F99\n"
    with pytest.raises(ErrorProtocolo, match="CRC"):
        parsear_linea(linea)


def test_trama_sin_delimitador_de_inicio_se_rechaza():
    with pytest.raises(ErrorProtocolo, match="inicia"):
        parsear_linea("57|CMD|nombre=AbrirTalanquera#9F98\n")


def test_trama_sin_salto_de_linea_final_se_rechaza():
    with pytest.raises(ErrorProtocolo, match="salto"):
        parsear_linea("^57|CMD|nombre=AbrirTalanquera#9F98")


def test_trama_con_seq_no_numerica_se_rechaza():
    cuerpo = "AA|CMD|nombre=AbrirTalanquera"
    crc = calcular_crc16(cuerpo.encode("ascii"))
    linea = f"^{cuerpo}#{crc:04X}\n"
    with pytest.raises(ErrorProtocolo, match="SEQ"):
        parsear_linea(linea)


def test_trama_con_seq_de_once_digitos_se_rechaza():
    cuerpo = "12345678901|PING|"
    crc = calcular_crc16(cuerpo.encode("ascii"))
    linea = f"^{cuerpo}#{crc:04X}\n"
    with pytest.raises(ErrorProtocolo, match="SEQ"):
        parsear_linea(linea)


def test_trama_con_tipo_desconocido_se_rechaza():
    cuerpo = "57|XXX|"
    crc = calcular_crc16(cuerpo.encode("ascii"))
    with pytest.raises(ErrorProtocolo, match="desconocido"):
        parsear_linea(f"^{cuerpo}#{crc:04X}\n")


def test_trama_con_campos_mal_formados_se_rechaza():
    cuerpo = "57|PING|nombreAbrirTalanquera"
    crc = calcular_crc16(cuerpo.encode("ascii"))
    with pytest.raises(ErrorProtocolo, match="clave"):
        parsear_linea(f"^{cuerpo}#{crc:04X}\n")


def test_analizador_descarta_bytes_sin_inicio_y_extrae_la_trama_siguiente():
    analizador = AnalizadorTramas()
    trama_valida = (
        Trama(seq=1042, tipo="PES", campos={"veh": "V02", "g": "100", "n": "1", "meseta": "1"})
        .armar_linea()
        .encode()
    )
    resultados = analizador.alimentar(b"ruido\n" + trama_valida)
    tramas = [r for r in resultados if isinstance(r, Trama)]
    descartes = [r for r in resultados if isinstance(r, TramaDescartada)]
    assert len(tramas) == 1
    assert len(descartes) == 1
    assert descartes[0].motivo == "bytes_sin_inicio"


def test_analizador_resincroniza_en_una_trama_corrompida():
    analizador = AnalizadorTramas()
    trama_buena = Trama(seq=5, tipo="EST", campos={"modo": "NORMAL"}).armar_linea().encode()
    # La primera trama se corta sin salto de línea y la segunda llega completa.
    corrompida = b"^999|EST|modo=DEGRA"
    resultados = analizador.alimentar(corrompida + trama_buena)
    tramas = [r for r in resultados if isinstance(r, Trama)]
    descartes = [r for r in resultados if isinstance(r, TramaDescartada)]
    assert len(tramas) == 1
    assert tramas[0].seq == 5
    # Los 19 bytes de la trama abandonada se cuentan como descarte, no desaparecen (§4.2 regla 3).
    assert len(descartes) == 1
    assert descartes[0].motivo == "trama_incompleta"


def test_analizador_cuenta_como_descarte_una_trama_abandonada_sin_salto_de_linea():
    # Reproduce el hallazgo de la revisión de Etapa 3: antes de la corrección, una
    # trama que empieza con '^' y nunca llega a su '\n' porque llega otro '^' antes
    # se perdía sin incrementar ningún contador (ni tramas_invalidas ni
    # bytes_descartados), lo que podía ocultar ruido de línea real durante una
    # operación prolongada (P01).
    analizador = AnalizadorTramas()
    abandonada = b"^999|EST|modo=DEGRA"
    resultados = analizador.alimentar(abandonada)
    assert resultados == []  # todavía no hay '^' siguiente: nada que reportar aún

    trama_buena = Trama(seq=1, tipo="PING", campos={}).armar_linea().encode()
    resultados = analizador.alimentar(trama_buena)
    descartes = [r for r in resultados if isinstance(r, TramaDescartada)]
    tramas = [r for r in resultados if isinstance(r, Trama)]
    assert len(descartes) == 1
    assert descartes[0].motivo == "trama_incompleta"
    assert str(len(abandonada)) in descartes[0].detalle
    assert len(tramas) == 1
    assert tramas[0].seq == 1


def test_analizador_no_reporta_descarte_entre_tramas_bien_formadas_consecutivas():
    # Dos tramas válidas pegadas (sin ruido entre ellas) no deben generar un
    # "trama_incompleta" espurio: la primera cierra normalmente con su '\n'
    # antes de que empiece la segunda.
    analizador = AnalizadorTramas()
    trama_1 = Trama(seq=1, tipo="EST", campos={"modo": "NORMAL"}).armar_linea().encode()
    trama_2 = Trama(seq=2, tipo="PING", campos={}).armar_linea().encode()
    resultados = analizador.alimentar(trama_1 + trama_2)
    descartes = [r for r in resultados if isinstance(r, TramaDescartada)]
    tramas = [r for r in resultados if isinstance(r, Trama)]
    assert descartes == []
    assert [t.seq for t in tramas] == [1, 2]


def test_analizador_descarta_trama_que_excede_longitud_sin_salto_de_linea():
    analizador = AnalizadorTramas(max_longitud_bytes=32)
    resultados = analizador.alimentar(b"^1|EST|" + b"x" * 40)
    descartes = [r for r in resultados if isinstance(r, TramaDescartada)]
    assert len(descartes) == 1
    assert descartes[0].motivo == "trama_excede_longitud"
    resultados_siguientes = analizador.alimentar(
        Trama(seq=1, tipo="PING", campos={}).armar_linea().encode()
    )
    tramas = [r for r in resultados_siguientes if isinstance(r, Trama)]
    assert len(tramas) == 1


def test_analizador_cuenta_trama_con_crc_invalido_como_invalida():
    analizador = AnalizadorTramas()
    resultados = analizador.alimentar(b"^57|CMD|nombre=AbrirTalanquera#0000\n")
    descartes = [r for r in resultados if isinstance(r, TramaDescartada)]
    assert len(descartes) == 1
    assert descartes[0].motivo == "trama_invalida"


def test_analizador_extrae_dos_tramas_pegadas_en_una_rafaga():
    analizador = AnalizadorTramas()
    dos_tramas = (
        Trama(seq=1, tipo="EST", campos={"modo": "NORMAL"}).armar_linea().encode()
        + Trama(seq=2, tipo="PING", campos={}).armar_linea().encode()
    )
    resultados = analizador.alimentar(dos_tramas)
    tramas = [r for r in resultados if isinstance(r, Trama)]
    assert [t.seq for t in tramas] == [1, 2]
