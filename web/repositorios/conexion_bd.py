"""Conexión SQLite compartida de la web (SPECS §19.2; CODESTYLE PY-6, PY-7, BD-2).

Un solo proceso dueño de una conexión con candado, igual que hace el puente
(``persistencia_sqlite``): waitress sirve cada petición en un hilo y todos
pasan por el mismo candado. La base es ``db/portus.db``, compartida con el
puente en modo WAL para permitir lector y escritor simultáneos.
"""

import logging
import sqlite3
import threading
from pathlib import Path

REGISTRO = logging.getLogger(__name__)

RUTA_ESQUEMA_POR_OMISION = Path(__file__).resolve().parent.parent.parent / "db" / "esquema.sql"
"""``db/esquema.sql`` relativo a este archivo, no al ``cwd`` del proceso: con
el layout del SPECS §19.2 (``/opt/portus/web/repositorios/conexion_bd.py`` y
``/opt/portus/db/esquema.sql``) resuelve igual que en el repositorio."""


def id_insertado(cursor: sqlite3.Cursor) -> int:
    """Id autogenerado del último INSERT del cursor (D-5: fallo explícito).

    ``lastrowid`` se tipa ``int | None`` porque es ``None`` antes del primer
    INSERT; tras un INSERT exitoso siempre está presente, así que la ausencia
    se eleva en lugar de inventar un id.
    """
    if cursor.lastrowid is None:
        mensaje = "el INSERT no devolvió un id autogenerado"
        raise RuntimeError(mensaje)
    return int(cursor.lastrowid)


class ConexionBd:
    """Abre la base, aplica el esquema y expone conexión + candado (BD-2)."""

    def __init__(self, ruta_bd: str, ruta_esquema: str | Path = RUTA_ESQUEMA_POR_OMISION) -> None:
        self._candado = threading.Lock()
        ruta = Path(ruta_bd)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conexion = sqlite3.connect(ruta, check_same_thread=False)
        except sqlite3.Error as error:
            mensaje = f"no se pudo abrir la base de datos '{ruta_bd}': {error}"
            raise RuntimeError(mensaje) from error
        # Filas accesibles por nombre de columna; los repositorios cuentan con ello.
        self._conexion.row_factory = sqlite3.Row
        esquema_sql = self._leer_esquema(Path(ruta_esquema))
        with self._candado:
            # WAL: el puente escribe eventos mientras la web lee (SPECS §19.2).
            self._conexion.execute("PRAGMA journal_mode=WAL")
            # FK desactivada durante la migración del esquema (DDL): la recreación
            # de ``manifiesto`` (migración 003) hace DROP+RENAME en cada arranque
            # y, con FK ON, el DROP dispara un DELETE implícito que violaría las
            # FK de ``solicitud_levante``/``cita`` que ya referencian a
            # ``manifiesto``. Se reactiva tras el esquema para el runtime (BD-3:
            # las claves foráneas se comprueban de verdad en los datos).
            self._conexion.execute("PRAGMA foreign_keys=OFF")
            self._conexion.executescript(esquema_sql)
            self._conexion.execute("PRAGMA foreign_keys=ON")
            self._conexion.commit()
        REGISTRO.info("Conexión web lista en %s (esquema: %s)", ruta_bd, ruta_esquema)

    @staticmethod
    def _leer_esquema(ruta: Path) -> str:
        if not ruta.is_file():
            mensaje = (
                f"no se encontró el esquema SQL '{ruta}'. "
                "Verifique que db/esquema.sql exista junto al servicio (CODESTYLE BD-2)."
            )
            raise RuntimeError(mensaje)
        return ruta.read_text(encoding="utf-8")

    @property
    def candado(self) -> threading.Lock:
        return self._candado

    @property
    def conexion(self) -> sqlite3.Connection:
        return self._conexion

    def cerrar(self) -> None:
        with self._candado:
            self._conexion.close()
