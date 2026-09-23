"""Siembra una operación de demostración completa para el simulador (SPECS §19.3).

Crea el manifiesto DEPOSITO para C01 con el vehículo V01 (peso declarado
38500 g, tara 950 g), el levante otorgado en canal verde y la cita programada
en la franja local vigente, de modo que el ciclo del simulador
(``herramientas/simulador_controlador.py``: GAR → PES → TRF → GRU → PAT →
GRU → PES → SAL) corra de punta a punta sin rechazos y se vea un turno real
en las pestañas Turnos/Retenciones/Patio/Grúa y el sinóptico en vivo.

Idempotente: se puede correr varias veces; reutiliza el manifiesto pendiente y
reposiciona la cita en la franja actual. Requiere haber corrido antes
``crear_usuarios_semilla`` y ``crear_datos_semilla``.

Uso::

    python -m herramientas.crear_operacion_demo --ruta-bd db/portus.db
"""

import argparse
import sqlite3
import sys
from datetime import UTC, datetime, timedelta, timezone

ZONA_LOCAL = timezone(timedelta(hours=-6))
"""Zona fija UTC-6 de la terminal (CODESTYLE I-8); las franjas se evalúan aquí."""

PESO_DECLARADO_G = 38500
TARA_V01_G = 950
TOLERANCIA_PCT = 5


def _franja_actual() -> tuple[str, str, str]:
    """(fecha, inicio, fin) de la franja de 15 min local vigente (§11.1)."""
    ahora = datetime.now(ZONA_LOCAL)
    minuto = ahora.minute - (ahora.minute % 15)
    inicio = ahora.replace(minute=minuto, second=0, microsecond=0)
    fin = inicio + timedelta(minutes=15)
    return inicio.strftime("%Y-%m-%d"), inicio.strftime("%H:%M"), fin.strftime("%H:%M")


def crear(ruta_bd: str) -> int:
    conexion = sqlite3.connect(ruta_bd)
    try:
        transportista = conexion.execute(
            "SELECT id FROM usuario WHERE username='transportista01'"
        ).fetchone()
        naviera = conexion.execute("SELECT id FROM usuario WHERE username='naviera01'").fetchone()
        if transportista is None or naviera is None:
            sys.stderr.write(
                "Falta la semilla de usuarios: corré antes "
                "`python -m herramientas.crear_usuarios_semilla --bd " + ruta_bd + "`.\n"
            )
            return 1
        tid, nid = int(transportista[0]), int(naviera[0])
        ahora_iso = datetime.now(UTC).isoformat()
        fecha, inicio, fin = _franja_actual()

        with conexion:
            # Catálogo mínimo (por si crear_datos_semilla no corrió).
            conexion.execute(
                "INSERT OR IGNORE INTO contenedor (id, descripcion) VALUES ('C01', 'demo')"
            )
            # V01 apuntando al transportista real y con la tara que asume el simulador (950).
            conexion.execute(
                "UPDATE vehiculo SET tara_g = ?, transportista_id = ? WHERE identificador = 'V01'",
                (TARA_V01_G, tid),
            )
            conexion.execute(
                "INSERT OR IGNORE INTO vehiculo (identificador, transportista_id, tara_g) "
                "VALUES ('V01', ?, ?)",
                (tid, TARA_V01_G),
            )

            # Manifiesto DEPOSITO pendiente para C01 (idempotente: reutiliza el sin_turno).
            fila = conexion.execute(
                "SELECT id FROM manifiesto WHERE contenedor_id = 'C01' "
                "AND estado_operativo = 'sin_turno'"
            ).fetchone()
            if fila is None:
                conexion.execute(
                    "INSERT INTO manifiesto (contenedor_id, naviera_id, transportista_id, "
                    "tipo_op, peso_declarado_g, tolerancia_pct, estado_documental, "
                    "estado_operativo, creado_en) "
                    "VALUES ('C01', ?, ?, 'DEPOSITO', ?, ?, 'levante_otorgado', 'sin_turno', ?)",
                    (nid, tid, PESO_DECLARADO_G, TOLERANCIA_PCT, ahora_iso),
                )
                fila = conexion.execute(
                    "SELECT id FROM manifiesto WHERE contenedor_id = 'C01' "
                    "AND estado_operativo = 'sin_turno'"
                ).fetchone()
            manifiesto_id = int(fila[0])

            # Levante otorgado en canal verde (idempotente).
            conexion.execute(
                "DELETE FROM solicitud_levante WHERE manifiesto_id = ?", (manifiesto_id,)
            )
            conexion.execute(
                "INSERT INTO solicitud_levante (manifiesto_id, estado, canal, "
                "solicitada_en, resuelta_en) VALUES (?, 'otorgada', 'verde', ?, ?)",
                (manifiesto_id, ahora_iso, ahora_iso),
            )

            # Franja local vigente + cita programada (reposiciona la existente a la ventana actual).
            conexion.execute(
                "INSERT OR IGNORE INTO franja (fecha, inicio, fin, capacidad, bloqueada) "
                "VALUES (?, ?, ?, 2, 0)",
                (fecha, inicio, fin),
            )
            cita = conexion.execute(
                "SELECT id FROM cita WHERE manifiesto_id = ? AND estado = 'programada'",
                (manifiesto_id,),
            ).fetchone()
            if cita is None:
                conexion.execute(
                    "INSERT INTO cita (manifiesto_id, transportista_id, franja_fecha, "
                    "franja_inicio, estado, creada_en) "
                    "VALUES (?, ?, ?, ?, 'programada', ?)",
                    (manifiesto_id, tid, fecha, inicio, ahora_iso),
                )
            else:
                conexion.execute(
                    "UPDATE cita SET franja_fecha = ?, franja_inicio = ? WHERE id = ?",
                    (fecha, inicio, int(cita[0])),
                )
        print(
            f"Operación demo sembrada en {ruta_bd}: V01→C01, manifiesto {manifiesto_id}, "
            f"levante otorgado (verde), cita {fecha} {inicio}."
        )
        print("Ahora arrancá el simulador para ver el ciclo GAR→PES→TRF→GRU→PAT→PES→SAL.")
        return 0
    except sqlite3.Error as error:
        sys.stderr.write(f"No se pudo sembrar la operación demo: {error}\n")
        return 1
    finally:
        conexion.close()


def main() -> int:
    analizador = argparse.ArgumentParser(description="Operación de demostración PORTUS")
    analizador.add_argument("--ruta-bd", default="db/portus.db", help="ruta de la base SQLite")
    return crear(analizador.parse_args().ruta_bd)


if __name__ == "__main__":
    raise SystemExit(main())
