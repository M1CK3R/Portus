"""Verificación de salida y cierre (SPECS §8.6): SAL, AL10, cierre y anulación."""

from pruebas.utilidades_logica import crear_logica, enviar, sembrar_operacion


def _turno_en_salida(logica):  # type: ignore[no-untyped-def]
    """Flujo completo hasta EnSalida: garita → pesaje → transferencia → grúa → pesaje salida."""
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    enviar(
        logica,
        "pesaje.medicion",
        {"veh": "V01", "peso_g": 38_600, "muestras": 10, "meseta": True},
        seq=2,
    )
    enviar(logica, "transferencia.evento", {"evento": "ALINEADO", "veh": "V01"}, seq=3)
    enviar(
        logica,
        "patio.cambio",
        {"posicion": "P1", "nivel": 1, "contenedor": "C01", "estado": "OCUPADA"},
        seq=4,
    )
    enviar(logica, "grua.paso", {"paso": "FIN", "resultado": "OK", "contenedor": "C01"}, seq=5)
    # Salida del depósito: el camión sale vacío, peso ≈ tara (950 g, dentro de 5 %).
    enviar(
        logica,
        "pesaje.medicion",
        {"veh": "V01", "peso_g": 960, "muestras": 8, "meseta": True},
        seq=6,
    )
    return logica.nucleo.turnos_repo.activo_de_vehiculo(1)


def test_sal_detectado_coincide_envia_abrir_puerta_salida(tmp_path) -> None:
    logica = crear_logica(tmp_path)
    _turno_en_salida(logica)
    enviar(logica, "salida.verificacion", {"veh": "V01", "res": "DETECTADO"}, seq=7)
    assert "AbrirPuertaSalida" in logica.publicador.nombres_de_comandos()  # §8.6.2


def test_sal_sin_turno_coincidente_genera_al10_y_no_autoriza(tmp_path) -> None:
    logica = crear_logica(tmp_path)
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    enviar(logica, "salida.verificacion", {"veh": "V01", "res": "DETECTADO"}, seq=2)
    with logica.bd.candado:
        al10 = logica.bd.conexion.execute(
            "SELECT COUNT(*) FROM alarma WHERE codigo = 'AL10'"
        ).fetchone()[0]
    assert al10 == 1  # §13.1: el servidor genera AL10
    assert "AbrirPuertaSalida" not in logica.publicador.nombres_de_comandos()


def test_sal_confirmado_cierra_turno_y_marca_cumplimiento(tmp_path) -> None:
    logica = crear_logica(tmp_path)
    _turno_en_salida(logica)
    enviar(logica, "salida.verificacion", {"veh": "V01", "res": "DETECTADO"}, seq=7)
    enviar(logica, "salida.verificacion", {"veh": "V01", "res": "CONFIRMADO"}, seq=8)
    with logica.bd.candado:
        estado, cerrado_en = logica.bd.conexion.execute(
            "SELECT estado, cerrado_en FROM turno"
        ).fetchone()
        cita = logica.bd.conexion.execute("SELECT estado, cumplida_en_ventana FROM cita").fetchone()
        activos = logica.bd.conexion.execute(
            "SELECT COUNT(*) FROM turno WHERE estado NOT IN ('Cerrado', 'Anulado')"
        ).fetchone()[0]
    assert estado == "Cerrado" and cerrado_en is not None
    assert tuple(cita) == ("cumplida", 1)  # §11.2 + A11
    assert activos == 0  # §8.2 regla 5: ningún turno abierto tras la salida
    notificaciones = logica.publicador.datos_de("notificacion.turno_completado")
    assert notificaciones and notificaciones[-1]["resultado"] == "completado"  # notificación 8
    aviso = notificaciones[-1]  # §15.3: vehículo, contenedor, tipo y tiempo total
    assert (aviso["vehiculo"], aviso["contenedor"], aviso["tipo_op"]) == ("V01", "C01", "DEPOSITO")
    assert isinstance(aviso["tiempo_total_s"], int) and aviso["tiempo_total_s"] >= 0


def test_sal_confirmado_sin_turno_en_salida_genera_al10(tmp_path) -> None:
    logica = crear_logica(tmp_path)
    enviar(logica, "salida.verificacion", {"veh": "V01", "res": "CONFIRMADO"}, seq=1)
    with logica.bd.candado:
        al10 = logica.bd.conexion.execute(
            "SELECT COUNT(*) FROM alarma WHERE codigo = 'AL10'"
        ).fetchone()[0]
    assert al10 == 1


def test_anulacion_autoriza_salida_sin_completar(tmp_path) -> None:
    """§8.2 regla 4: Anulado es final; la salida se autoriza sin completar (§8.6.3)."""
    logica = crear_logica(tmp_path)
    turno = _turno_directo_de_garita(logica)
    logica.nucleo.maquina.anular(turno, "reclamo del cliente", "web")
    logica.nucleo.salida.autorizar_salida_anulacion(turno)
    assert "AbrirPuertaSalida" in logica.publicador.nombres_de_comandos()  # §8.6.3
    notificaciones = logica.publicador.datos_de("notificacion.turno_anulado")
    assert notificaciones[-1]["resultado"] == "anulado"  # notificación 9


def _turno_directo_de_garita(logica):  # type: ignore[no-untyped-def]
    """Turno activo en EnGarita (la anulación parte de un estado activo, §8.1)."""
    sembrar_operacion(logica)
    enviar(logica, "garita.identificacion", {"veh": "V01"}, seq=1)
    turno = logica.nucleo.turnos_repo.activo_de_vehiculo(1)
    assert turno is not None
    return turno


def test_sal_con_resultado_desconocido_se_descarta(tmp_path) -> None:
    logica = crear_logica(tmp_path)
    enviar(logica, "salida.verificacion", {"veh": "V01", "res": "RARO"}, seq=1)
    assert "AbrirPuertaSalida" not in logica.publicador.nombres_de_comandos()
    with logica.bd.candado:
        alarmas = logica.bd.conexion.execute("SELECT COUNT(*) FROM alarma").fetchone()[0]
    assert alarmas == 0


def test_sal_acepta_campo_resultado_del_puente(tmp_path) -> None:
    """El puente publica el SAL con ``resultado`` (no ``res``); el nucleo debe aceptarlo (§4.4)."""
    logica = crear_logica(tmp_path)
    turno = _turno_en_salida(logica)
    # Formato real del puente: campo ``resultado`` (mensajes_mqtt renombra res→resultado).
    enviar(logica, "salida.verificacion", {"veh": "V01", "resultado": "DETECTADO"}, seq=7)
    assert "AbrirPuertaSalida" in logica.publicador.nombres_de_comandos()  # §8.6.2
    enviar(logica, "salida.verificacion", {"veh": "V01", "resultado": "CONFIRMADO"}, seq=8)
    turno = logica.nucleo.turnos_repo.buscar_por_id(turno.id)
    assert turno is not None and turno.estado.value == "Cerrado"  # §8.2 regla 5
