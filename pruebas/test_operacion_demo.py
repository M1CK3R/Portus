"""Operación demo + secuencia del simulador de punta a punta (Etapa 6, §19.3).

Verifica que ``crear_operacion_demo`` siembra lo justo (manifiesto, levante
otorgado y cita en la franja vigente) para que el ciclo del simulador
(GAR → PES → TRF → GRU → PAT → GRU → PES → SAL) corra sin rechazos y el
turno llegue a ``Cerrado``. Es la prueba de que "simular datos" funciona.
"""

import json
from datetime import UTC
from pathlib import Path

from herramientas.crear_datos_semilla import crear as crear_datos
from herramientas.crear_operacion_demo import OpcionesDemo
from herramientas.crear_operacion_demo import crear as crear_operacion
from pruebas.utilidades_logica import PublicadorCapturado
from pruebas.utilidades_web import crear_web
from web.aplicacion import crear_aplicacion
from web.contexto import CLAVE_CONTEXTO
from web.modelos.usuario import Rol
from web.servicios.nucleo_logica import NucleoLogica
from web.tiempo import marca_utc


def _enviar(nucleo: NucleoLogica, tipo: str, datos: dict[str, object], seq: int) -> None:
    """Alimenta un evento al nucleo como si llegara por MQTT (envoltorio §5.2)."""
    contenido = {
        "id": f"evt-{tipo}-{seq}",
        "ts": "2026-09-20T14:03:22.418Z",
        "origen": "controlador",
        "tipo": tipo,
        "seq": seq,
        "datos": datos,
    }
    topico = "portus/evt/" + tipo.split(".")[0]
    nucleo.atender_mensaje(topico, json.dumps(contenido).encode("utf-8"))


def test_el_ciclo_del_simulador_cierra_el_turno(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # 1. App de prueba sobre su BD temporal (aplica el esquema y abre el nucleo).
    env = crear_web(Path(tmp_path))
    configuracion = env.app.extensions[CLAVE_CONTEXTO].configuracion
    ruta_bd = configuracion.ruta_bd

    # 2. Siembra usuarios + catálogo + operación demo en el MISMO archivo.
    env.usuarios.crear("transportista01", "x", Rol.TRANSPORTISTA, "Transportista 1", marca_utc())
    env.usuarios.crear("naviera01", "x", Rol.NAVIERA, "Naviera A", marca_utc())
    crear_datos(ruta_bd)
    crear_operacion(ruta_bd, OpcionesDemo(con_cita=True))  # sin bot: sustituto H3

    # 3. Reconstruye la app con un publicador capturado (sobre la misma BD).
    # Usa un reloj real (no el falso) porque la cita del demo se siembra en la
    # franja local actual y la validación de ventana (§11.1) compara con "ahora".
    from datetime import datetime

    publicador = PublicadorCapturado()
    env.app = crear_aplicacion(
        configuracion,
        env.bd,
        reloj_epoch=env.reloj_epoch,
        fabrica_instante=lambda: datetime.now(UTC),
        publicador_logica=publicador,
    )
    nucleo = env.app.extensions[CLAVE_CONTEXTO].nucleo

    # 1. GAR: el controlador identifica a V01; el servidor valida y autoriza.
    _enviar(nucleo, "garita.identificacion", {"veh": "V01"}, seq=1)
    turno = nucleo.maquina.buscar_turno(1)
    assert turno is not None
    assert turno.estado.value == "EnGarita"  # nació autorizado, no rechazado

    # 2. PES de entrada dentro de tolerancia (38500 vs declarado 38500, tara 950).
    _enviar(
        nucleo,
        "pesaje.medicion",
        {"veh": "V01", "peso_g": 38500, "muestras": 12, "meseta": True},
        seq=2,
    )
    turno = nucleo.maquina.buscar_turno(1)
    assert turno is not None and turno.estado.value == "EnRuta"

    # 3. TRF alineado → EnTransferencia y arranca el JOB de depósito.
    _enviar(nucleo, "transferencia.evento", {"evento": "ALINEADO", "veh": "V01"}, seq=3)
    turno = nucleo.maquina.buscar_turno(1)
    assert turno is not None and turno.estado.value == "EnTransferencia"

    # 4-5. PAT + GRU FIN: el depósito se confirma físicamente.
    _enviar(
        nucleo,
        "patio.cambio",
        {"posicion": "P3", "nivel": 1, "contenedor": "C01", "estado": "OCUPADA"},
        seq=4,
    )
    _enviar(
        nucleo,
        "grua.paso",
        {"paso": "FIN", "resultado": "OK", "contenedor": "C01"},
        seq=5,
    )
    turno = nucleo.maquina.buscar_turno(1)
    assert turno is not None and turno.estado.value == "EnPesajeSalida"

    # 6. PES de salida (camión vacío, peso ≈ tara 950) dentro de tolerancia.
    _enviar(
        nucleo,
        "pesaje.medicion",
        {"veh": "V01", "peso_g": 950, "muestras": 10, "meseta": True},
        seq=6,
    )
    turno = nucleo.maquina.buscar_turno(1)
    assert turno is not None and turno.estado.value == "EnSalida"

    # 7-8. SAL: detección y confirmación cierran el turno.
    _enviar(nucleo, "salida.verificacion", {"veh": "V01", "res": "DETECTADO"}, seq=7)
    _enviar(nucleo, "salida.verificacion", {"veh": "V01", "res": "CONFIRMADO"}, seq=8)
    turno = nucleo.maquina.buscar_turno(1)
    assert turno is not None and turno.estado.value == "Cerrado"
    # El ciclo de grúa quedó registrado para métricas y gráfica (§12.6).
    assert "AbrirPuertaSalida" in publicador.nombres_de_comandos()
