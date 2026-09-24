"""Siembra una operación de **desarrollo** lista para el simulador (SPECS §19.3).

Por omisión crea el manifiesto DEPOSITO de C01 para el vehículo V01 (peso
declarado 38500 g, tara 950 g) con el levante otorgado en canal verde. La
cita **no** se crea: el transportista la pide con ``/cita`` en el bot, como
exige la barrera 🔴 4 del ROADMAP (la operación se origina en la plataforma).

``--con-cita`` es el sustituto temporal del hito H3 (Etapa 11) para probar sin
Telegram: escribe la cita directo en la base, avisa que es solo desarrollo y
**no se usa en la evaluación**. Las demás opciones preparan los caminos de la
prueba de punta a punta:

* ``--canal rojo``        → RT03 tras el pesaje de entrada (§9.2).
* ``--fuera-de-ventana``  → con ``--con-cita``, la cita queda en una franja ya
  cerrada: la tarea de vencimiento la pasa a ``vencida`` y la garita aplica RT04
  (§11.1 regla 7).
* ``--tipo RETIRO``       → retiro de un contenedor que ya está en el patio (§12.5).
* ``--vehiculo``/``--contenedor`` → otra pareja; el manifiesto va al dueño del vehículo.

Idempotente: reutiliza el manifiesto pendiente del contenedor y reposiciona la
cita. Requiere haber corrido antes ``crear_usuarios_semilla`` y
``crear_datos_semilla``. Uso::

    python -m herramientas.crear_operacion_demo --ruta-bd db/portus.db
    python -m herramientas.crear_operacion_demo --con-cita --vehiculo V03 --canal rojo
"""

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

ZONA_LOCAL = timezone(timedelta(hours=-6))
"""Zona fija UTC-6 de la terminal (CODESTYLE I-8); las franjas se evalúan aquí."""

PESO_DECLARADO_G = 38500
TARA_V01_G = 950
TOLERANCIA_PCT = 5
DURACION_FRANJA_MIN = 15
FRANJAS_ATRAS_FUERA_DE_VENTANA = 2
"""Dos franjas atrás: la ventana (fin + 5 min, §11.1) ya cerró al presentarse."""
TRANSPORTISTA_POR_OMISION = "transportista01"
AVISO_CITA_DE_DESARROLLO = (
    "AVISO: --con-cita escribe la cita directo en la base (sustituto temporal del hito H3). "
    "Solo desarrollo: en la evaluación la cita se pide con /cita (barrera 4 del ROADMAP).\n"
)


class ErrorOperacionDemo(Exception):
    """La semilla previa falta o la operación pedida no es posible (D-7)."""


@dataclass(frozen=True)
class OpcionesDemo:
    """Qué operación sembrar; los valores por omisión son el happy path de depósito."""

    vehiculo: str = "V01"
    contenedor: str = "C01"
    tipo_op: str = "DEPOSITO"
    canal: str = "verde"
    fuera_de_ventana: bool = False
    peso_declarado_g: int = PESO_DECLARADO_G
    con_cita: bool = False
    """Solo desarrollo: sin bot, la cita se escribe en la base (hito H3)."""


def _franja(atras: int = 0) -> tuple[str, str]:
    """(fecha, inicio) local de la franja vigente o de ``atras`` franjas antes (§11.1)."""
    ahora = datetime.now(ZONA_LOCAL) - timedelta(minutes=DURACION_FRANJA_MIN * atras)
    minuto = ahora.minute - (ahora.minute % DURACION_FRANJA_MIN)
    inicio = ahora.replace(minute=minuto, second=0, microsecond=0)
    return inicio.strftime("%Y-%m-%d"), inicio.strftime("%H:%M")


def _fin(inicio: str) -> str:
    hora, minuto = (int(parte) for parte in inicio.split(":"))
    total = hora * 60 + minuto + DURACION_FRANJA_MIN
    return f"{total // 60 % 24:02d}:{total % 60:02d}"


def _id_usuario(conexion: sqlite3.Connection, username: str) -> int:
    fila = conexion.execute("SELECT id FROM usuario WHERE username = ?", (username,)).fetchone()
    if fila is None:
        raise ErrorOperacionDemo(
            f"falta el usuario '{username}': corra antes "
            "`python -m herramientas.crear_usuarios_semilla`"
        )
    return int(fila[0])


def _dueno_del_vehiculo(conexion: sqlite3.Connection, vehiculo: str) -> int:
    """Transportista del vehículo; V01 se crea o ajusta con la tara del simulador."""
    if vehiculo == "V01":
        tid = _id_usuario(conexion, TRANSPORTISTA_POR_OMISION)
        conexion.execute(
            "INSERT INTO vehiculo (identificador, transportista_id, tara_g) "
            "VALUES ('V01', ?, ?) ON CONFLICT (identificador) DO UPDATE SET "
            "transportista_id = excluded.transportista_id, tara_g = excluded.tara_g",
            (tid, TARA_V01_G),
        )
        return tid
    fila = conexion.execute(
        "SELECT transportista_id FROM vehiculo WHERE identificador = ?", (vehiculo,)
    ).fetchone()
    if fila is None:
        raise ErrorOperacionDemo(
            f"el vehículo '{vehiculo}' no existe: corra antes "
            "`python -m herramientas.crear_datos_semilla`"
        )
    return int(fila[0])


def _manifiesto(
    conexion: sqlite3.Connection, opciones: OpcionesDemo, naviera_id: int, tid: int, ahora: str
) -> int:
    """Manifiesto pendiente del contenedor con levante otorgado (idempotente)."""
    if opciones.tipo_op == "RETIRO":
        en_patio = conexion.execute(
            "SELECT 1 FROM inventario WHERE contenedor_id = ?", (opciones.contenedor,)
        ).fetchone()
        if en_patio is None:
            raise ErrorOperacionDemo(
                f"RETIRO de {opciones.contenedor}: el contenedor no está en el patio; "
                "deposítelo antes (§12.5)"
            )
    fila = conexion.execute(
        "SELECT id FROM manifiesto WHERE contenedor_id = ? AND estado_operativo = 'sin_turno'",
        (opciones.contenedor,),
    ).fetchone()
    if fila is None:
        cursor = conexion.execute(
            "INSERT INTO manifiesto (contenedor_id, naviera_id, transportista_id, tipo_op, "
            "peso_declarado_g, tolerancia_pct, estado_documental, estado_operativo, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, 'levante_otorgado', 'sin_turno', ?)",
            (
                opciones.contenedor,
                naviera_id,
                tid,
                opciones.tipo_op,
                opciones.peso_declarado_g,
                TOLERANCIA_PCT,
                ahora,
            ),
        )
        manifiesto_id = int(cursor.lastrowid or 0)
    else:
        manifiesto_id = int(fila[0])
        conexion.execute(
            "UPDATE manifiesto SET transportista_id = ?, tipo_op = ?, peso_declarado_g = ?, "
            "estado_documental = 'levante_otorgado' WHERE id = ?",
            (tid, opciones.tipo_op, opciones.peso_declarado_g, manifiesto_id),
        )
    conexion.execute("DELETE FROM solicitud_levante WHERE manifiesto_id = ?", (manifiesto_id,))
    conexion.execute(
        "INSERT INTO solicitud_levante (manifiesto_id, estado, canal, solicitada_en, "
        "resuelta_en) VALUES (?, 'otorgada', ?, ?, ?)",
        (manifiesto_id, opciones.canal, ahora, ahora),
    )
    return manifiesto_id


def _cita(
    conexion: sqlite3.Connection, manifiesto_id: int, tid: int, fuera: bool, ahora: str
) -> tuple[str, str]:
    """Cita programada en la franja vigente (o en una vencida para RT04)."""
    fecha, inicio = _franja(FRANJAS_ATRAS_FUERA_DE_VENTANA if fuera else 0)
    conexion.execute(
        "INSERT OR IGNORE INTO franja (fecha, inicio, fin, capacidad, bloqueada) "
        "VALUES (?, ?, ?, 2, 0)",
        (fecha, inicio, _fin(inicio)),
    )
    cita = conexion.execute(
        "SELECT id FROM cita WHERE manifiesto_id = ? AND estado = 'programada'",
        (manifiesto_id,),
    ).fetchone()
    if cita is None:
        conexion.execute(
            "INSERT INTO cita (manifiesto_id, transportista_id, franja_fecha, franja_inicio, "
            "estado, creada_en) VALUES (?, ?, ?, ?, 'programada', ?)",
            (manifiesto_id, tid, fecha, inicio, ahora),
        )
    else:
        conexion.execute(
            "UPDATE cita SET franja_fecha = ?, franja_inicio = ? WHERE id = ?",
            (fecha, inicio, int(cita[0])),
        )
    return fecha, inicio


def _manifiesto_para_agente(conexion: sqlite3.Connection, naviera_id: int, tid: int) -> None:
    """C02 en 'declarado' (sin levante) para practicar el flujo del AGENTE (§9.1)."""
    conexion.execute("INSERT OR IGNORE INTO contenedor (id, descripcion) VALUES ('C02', 'demo')")
    existe = conexion.execute(
        "SELECT 1 FROM manifiesto WHERE contenedor_id = 'C02' AND estado_operativo = 'sin_turno'"
    ).fetchone()
    if existe is None:
        conexion.execute(
            "INSERT INTO manifiesto (contenedor_id, naviera_id, transportista_id, tipo_op, "
            "peso_declarado_g, tolerancia_pct, estado_documental, estado_operativo, creado_en) "
            "VALUES ('C02', ?, ?, 'DEPOSITO', 25000, 5, 'declarado', 'sin_turno', ?)",
            (naviera_id, tid, datetime.now(UTC).isoformat()),
        )


def crear(ruta_bd: str, opciones: OpcionesDemo | None = None) -> int:
    """Siembra la operación; devuelve 0 si quedó lista y 1 si falta algo (con causa)."""
    opciones = opciones or OpcionesDemo()
    conexion = sqlite3.connect(ruta_bd)
    try:
        with conexion:
            naviera_id = _id_usuario(conexion, "naviera01")
            tid = _dueno_del_vehiculo(conexion, opciones.vehiculo)
            conexion.execute(
                "INSERT OR IGNORE INTO contenedor (id, descripcion) VALUES (?, 'demo')",
                (opciones.contenedor,),
            )
            ahora = datetime.now(UTC).isoformat()
            manifiesto_id = _manifiesto(conexion, opciones, naviera_id, tid, ahora)
            cita = (
                _cita(conexion, manifiesto_id, tid, opciones.fuera_de_ventana, ahora)
                if opciones.con_cita
                else None
            )
            if opciones.vehiculo == "V01" and opciones.contenedor == "C01":
                _manifiesto_para_agente(conexion, naviera_id, tid)
    except (ErrorOperacionDemo, sqlite3.Error) as error:
        sys.stderr.write(f"No se pudo sembrar la operación demo: {error}\n")
        return 1
    finally:
        conexion.close()
    if cita is None:
        detalle_cita = "sin cita: el transportista la pide con /cita en el bot"
    else:
        ventana = "ventana cerrada (RT04)" if opciones.fuera_de_ventana else "vigente"
        detalle_cita = f"cita {cita[0]} {cita[1]} ({ventana})"
        sys.stderr.write(AVISO_CITA_DE_DESARROLLO)
    print(
        f"Operación lista en {ruta_bd}: {opciones.vehiculo}→{opciones.contenedor} "
        f"{opciones.tipo_op}, manifiesto {manifiesto_id}, levante otorgado "
        f"({opciones.canal}), {detalle_cita}."
    )
    return 0


def main() -> int:
    analizador = argparse.ArgumentParser(description="Operación de demostración PORTUS")
    analizador.add_argument("--ruta-bd", default="db/portus.db", help="ruta de la base SQLite")
    analizador.add_argument("--vehiculo", default="V01")
    analizador.add_argument("--contenedor", default="C01")
    analizador.add_argument("--tipo", choices=["DEPOSITO", "RETIRO"], default="DEPOSITO")
    analizador.add_argument("--canal", choices=["verde", "rojo"], default="verde")
    analizador.add_argument(
        "--con-cita",
        action="store_true",
        help="solo desarrollo: crea la cita sin el bot (prohibido en la evaluación)",
    )
    analizador.add_argument("--fuera-de-ventana", action="store_true")
    analizador.add_argument("--peso-declarado-g", type=int, default=PESO_DECLARADO_G)
    argumentos = analizador.parse_args()
    return crear(
        argumentos.ruta_bd,
        OpcionesDemo(
            vehiculo=argumentos.vehiculo,
            contenedor=argumentos.contenedor,
            tipo_op=argumentos.tipo,
            canal=argumentos.canal,
            fuera_de_ventana=argumentos.fuera_de_ventana,
            peso_declarado_g=argumentos.peso_declarado_g,
            con_cita=argumentos.con_cita,
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
