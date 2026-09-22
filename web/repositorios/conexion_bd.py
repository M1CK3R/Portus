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
            # Las claves foráneas se comprueban de verdad (CODESTYLE BD-3).
            self._conexion.execute("PRAGMA foreign_keys=ON")
            self._conexion.executescript(esquema_sql)
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
