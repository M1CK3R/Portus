"""Regenera ``db/esquema.sql`` a partir de ``db/migraciones/`` (CODESTYLE BD-2).

El esquema es la concatenación ordenada de las migraciones numeradas, cada una
bajo su encabezado; nadie lo edita a mano. ``pruebas/test_esquema_regenerado``
falla si el archivo versionado se desvía de las migraciones. Uso::

    python -m herramientas.regenerar_esquema
"""

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTA_MIGRACIONES = RAIZ / "db" / "migraciones"
RUTA_ESQUEMA = RAIZ / "db" / "esquema.sql"
SEPARADOR = "-- " + "=" * 76
NOMBRES_POR_LINEA = 3


def generar(ruta_migraciones: Path = RUTA_MIGRACIONES) -> str:
    """Texto completo del esquema con LF y un salto de línea final (F-4)."""
    migraciones = sorted(ruta_migraciones.glob("[0-9][0-9][0-9]_*.sql"))
    if not migraciones:
        mensaje = f"no hay migraciones numeradas en '{ruta_migraciones}'"
        raise FileNotFoundError(mensaje)
    nombres = [ruta.name for ruta in migraciones]
    lineas_nombres = [
        ", ".join(nombres[inicio : inicio + NOMBRES_POR_LINEA])
        for inicio in range(0, len(nombres), NOMBRES_POR_LINEA)
    ]
    encabezado = [
        "-- esquema.sql PORTUS — regenerado a partir de db/migraciones/ (CODESTYLE BD-2).",
        "-- NO editar a mano: se regenera con `python -m herramientas.regenerar_esquema`.",
        f"-- Migraciones incluidas: {lineas_nombres[0]}" + ("," if len(lineas_nombres) > 1 else ""),
    ]
    for indice, linea in enumerate(lineas_nombres[1:], start=1):
        coma = "," if indice < len(lineas_nombres) - 1 else ""
        encabezado.append(f"--   {linea}{coma}")
    bloques = ["\n".join(encabezado)]
    for ruta in migraciones:
        contenido = ruta.read_text(encoding="utf-8").replace("\r\n", "\n").strip("\n")
        bloques.append(f"{SEPARADOR}\n-- {ruta.name}\n{SEPARADOR}\n{contenido}")
    return "\n\n".join(bloques) + "\n"


def main() -> int:
    analizador = argparse.ArgumentParser(description="Regenera db/esquema.sql (BD-2)")
    analizador.add_argument(
        "--verificar",
        action="store_true",
        help="no escribe; termina con código 1 si esquema.sql está desactualizado",
    )
    argumentos = analizador.parse_args()
    esperado = generar()
    if argumentos.verificar:
        actual = RUTA_ESQUEMA.read_bytes().decode("utf-8").replace("\r\n", "\n")
        if actual != esperado:
            sys.stderr.write("db/esquema.sql no coincide con db/migraciones/: regenérelo\n")
            return 1
        return 0
    # newline="\n": LF en cualquier sistema operativo (F-4).
    with RUTA_ESQUEMA.open("w", encoding="utf-8", newline="\n") as archivo:
        archivo.write(esperado)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
