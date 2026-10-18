"""Reproduce una captura de tramas contra el puente sin la maqueta (CODESTYLE D-11).

Cada línea del archivo de captura puede ser una trama ``^SEQ|TIPO|CAMPOS#CRC\\n``
o el formato ``<retardo_ms>|<trama>`` para simular tiempos. Con ``--analizar``
valida y muestra el envoltorio JSON que el puente publicaría, sin serial.

Ejemplo:
    python herramientas/reproducir_captura.py --analizar captura.txt
    python herramientas/reproducir_captura.py --puerto /dev/pts/3 captura.txt
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from puente.enlace_serie import EnlaceSerie
from puente.mensajes_mqtt import marca_tiempo_utc, mensaje_de_trama, serializar_mensaje
from puente.protocolo import AnalizadorTramas, Trama

REGISTRO = logging.getLogger("reproducir")


def _retardo_de_linea(linea: str) -> tuple[int, str]:
    if "|" in linea and linea.split("|", 1)[0].isdigit() and not linea.startswith("^"):
        retardo, _, trama = linea.partition("|")
        return int(retardo), trama
    return 0, linea


def _cargar_captura(ruta: str) -> list[tuple[int, str]]:
    lineas: list[tuple[int, str]] = []
    for linea in Path(ruta).read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        retardo, trama = _retardo_de_linea(linea)
        lineas.append((retardo, trama))
    return lineas


def _analizar_captura(lineas: list[tuple[int, str]]) -> int:
    analizador = AnalizadorTramas()
    procesadas = 0
    for _, trama_texto in lineas:
        for resultado in analizador.alimentar(trama_texto.encode("ascii")):
            if isinstance(resultado, Trama):
                mensaje = mensaje_de_trama(resultado, marca_tiempo_utc())
                print(serializar_mensaje(mensaje))
                procesadas += 1
            else:
                REGISTRO.warning("Descartada: %s", resultado.detalle)
    return procesadas


def _enviar_captura(lineas: list[tuple[int, str]], ruta_puerto: str, baudios: int) -> None:
    enlace = EnlaceSerie(ruta_puerto, baudios)
    enlace.abrir()
    try:
        for retardo_ms, trama_texto in lineas:
            if retardo_ms:
                time.sleep(retardo_ms / 1000)
            enlace.escribir((trama_texto + "\n").encode("ascii"))
            REGISTRO.info("Enviada: %s", trama_texto)
    finally:
        enlace.cerrar()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s · %(message)s")
    analizador_argumentos = argparse.ArgumentParser(description="Reproduce una captura de tramas")
    analizador_argumentos.add_argument("captura", help="archivo con las tramas capturadas")
    analizador_argumentos.add_argument("--puerto", help="puerto serie destino (opcional)")
    analizador_argumentos.add_argument("--baudios", type=int, default=115200)
    analizador_argumentos.add_argument(
        "--analizar", action="store_true", help="valida y muestra el envoltorio JSON"
    )
    argumentos = analizador_argumentos.parse_args()
    lineas = _cargar_captura(argumentos.captura)
    if argumentos.analizar or argumentos.puerto is None:
        procesadas = _analizar_captura(lineas)
        print(f"Tramas procesadas: {procesadas}")
        return 0
    _enviar_captura(lineas, argumentos.puerto, argumentos.baudios)
    return 0


if __name__ == "__main__":
    sys.exit(main())
