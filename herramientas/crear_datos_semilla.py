"""Datos semilla del sistema (SPECS §19.3, ROADMAP Etapa 3/5; CODESTYLE S-1).

Crea el catálogo mínimo para operar sin registros precargados de operación
(barrera 🔴 4: la operación demostrada se origina desde la plataforma):

* contenedores del catálogo de la maqueta,
* vehículos con su identificador de garita y tara (A4),
* posiciones del patio lineal (por omisión P1-P4).

Las plazas 1-3 del parqueo nacen con el esquema (migración 003) y los 7
usuarios los crea ``crear_usuarios_semilla.py``. Uso::

    python herramientas/crear_datos_semilla.py --ruta-bd db/portus.db
"""

import argparse
import sqlite3
import sys

CONTENEDORES = ["C01", "C02", "C03", "C04"]
VEHICULOS = [("V01", 1, 900), ("V02", 1, 950), ("V03", 2, 880)]
"""(identificador, transportista_id del usuario semilla, tara_g)."""

POSICIONES = ["P1", "P2", "P3", "P4"]


def crear(ruta_bd: str) -> None:
    conexion = sqlite3.connect(ruta_bd)
    try:
        with conexion:
            for contenedor in CONTENEDORES:
                conexion.execute(
                    "INSERT OR IGNORE INTO contenedor (id, descripcion) VALUES (?, ?)",
                    (contenedor, f"Contenedor de la maqueta {contenedor}"),
                )
            for identificador, transportista_id, tara_g in VEHICULOS:
                conexion.execute(
                    "INSERT OR IGNORE INTO vehiculo (identificador, transportista_id, tara_g) "
                    "VALUES (?, ?, ?)",
                    (identificador, transportista_id, tara_g),
                )
            for posicion in POSICIONES:
                conexion.execute(
                    "INSERT OR IGNORE INTO posicion_patio (id, estado) VALUES (?, 'libre')",
                    (posicion,),
                )
    finally:
        conexion.close()
    print(f"Semilla creada en {ruta_bd}: contenedores, vehículos y posiciones del patio")


def main() -> int:
    analizador = argparse.ArgumentParser(description="Datos semilla de PORTUS")
    analizador.add_argument("--ruta-bd", default="db/portus.db")
    argumentos = analizador.parse_args()
    try:
        crear(argumentos.ruta_bd)
    except sqlite3.Error as error:
        sys.stderr.write(f"No se pudo crear la semilla: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
