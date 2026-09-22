"""Persistencia de eventos, telemetría y comandos en SQLite (SPECS §5.7, §17).

Consume todo lo publicado bajo ``portus/#`` y lo guarda con deduplicación por
``id`` (SPECS §5.5): una retransmisión tras SYN o una entrega duplicada del
broker no crea filas extra. Mantiene además la marca del último latido para
la AL01 retroactiva del arranque (SPECS §25 A14) y la trazabilidad de
comandos remotos (SPECS §17 ``comando``).

Las consultas y escrituras están siempre parametrizadas (CODESTYLE BD-1) y
las marcas de tiempo se guardan en UTC (BD-5).

El esquema NO se repite aquí como una constante de Python: se lee de
``db/esquema.sql`` en tiempo de ejecución (CODESTYLE BD-2, A-6 — una sola
fuente de verdad). Antes esta clase traía su propia copia del DDL, separada
de ``db/esquema.sql`` y de la migración; si alguien agregaba una columna o un
índice solo en el archivo SQL, el puente en ejecución nunca lo habría creado.
"""

import json
import logging
import sqlite3
import threading
from pathlib import Path

REGISTRO = logging.getLogger(__name__)

RUTA_ESQUEMA_POR_OMISION = Path(__file__).resolve().parent.parent / "db" / "esquema.sql"
"""Ubicación de ``db/esquema.sql`` relativa a este archivo, no al directorio
de trabajo del proceso. Con el layout de despliegue del SPECS §19.2
(``/opt/portus/puente/persistencia_sqlite.py`` y
``/opt/portus/db/esquema.sql``) resuelve igual que en el repositorio, sin
depender de con qué ``cwd`` se invoque ``python -m puente``."""


class PersistenciaSqlite:
    """Repositorio del puente: único lugar con SQL del servicio (CODESTYLE A-2)."""

    def __init__(self, ruta_bd: str, ruta_esquema: str | Path = RUTA_ESQUEMA_POR_OMISION) -> None:
        self._candado = threading.Lock()
        try:
            self._conexion = sqlite3.connect(ruta_bd, check_same_thread=False)
        except sqlite3.Error as error:
            mensaje = f"no se pudo abrir la base de datos '{ruta_bd}': {error}"
            raise RuntimeError(mensaje) from error
        esquema_sql = self._leer_esquema(ruta_esquema)
        with self._candado:
            self._conexion.executescript(esquema_sql)
            self._conexion.execute(
                "INSERT OR IGNORE INTO estado_enlace (id, enlace_estado, actualizado_en) "
                "VALUES (1, 'activo', '')"
            )
            self._conexion.commit()
        REGISTRO.info("Persistencia lista en %s (esquema: %s)", ruta_bd, ruta_esquema)

    @staticmethod
    def _leer_esquema(ruta_esquema: str | Path) -> str:
        ruta = Path(ruta_esquema)
        if not ruta.is_file():
            mensaje = (
                f"no se encontró el esquema SQL '{ruta}'. "
                "Verifique que db/esquema.sql exista junto al puente (CODESTYLE BD-2)."
            )
            raise RuntimeError(mensaje)
        return ruta.read_text(encoding="utf-8")

    def cerrar(self) -> None:
        with self._candado:
            self._conexion.close()

    def guardar_evento(
        self,
        mensaje_id: str,
        ts: str,
        origen: str,
        tipo: str,
        seq: int | None,
        datos: dict[str, object],
        topico: str,
    ) -> bool:
        """Inserta el evento con deduplicación por id; devuelve True si es nuevo."""
        datos_json = json.dumps(datos, ensure_ascii=False)
        with self._candado:
            cursor = self._conexion.execute(
                "INSERT OR IGNORE INTO evento (id, ts, origen, tipo, seq, datos, topico) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (mensaje_id, ts, origen, tipo, seq, datos_json, topico),
            )
            self._conexion.commit()
        insertado = cursor.rowcount > 0
        if not insertado:
            REGISTRO.debug("Evento duplicado descartado: id=%s", mensaje_id)
        return insertado

    def guardar_telemetria(
        self, telemetria_id: str, ts: str, tipo: str, valor: dict[str, object] | str
    ) -> None:
        """Guarda una muestra de telemetría con deduplicación por id (§5.7).

        Nota de alcance (Etapa 3): la tabla y este método ya existen y están
        probados (``test_persistencia_sqlite``), pero ningún productor los
        invoca todavía — el puente no genera telemetría de negocio propia
        (p. ej. longitud de la fila de espera); eso nace en la lógica de
        negocio de etapas posteriores (§16, Etapa 11) y llegará por
        ``portus/#`` como cualquier otro mensaje. No es código muerto por
        error: es la interfaz ya lista para cuando exista ese productor.
        """
        valor_json = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)
        with self._candado:
            self._conexion.execute(
                "INSERT OR IGNORE INTO telemetria (id, ts, tipo, valor) VALUES (?, ?, ?, ?)",
                (telemetria_id, ts, tipo, valor_json),
            )
            self._conexion.commit()

    def registrar_comando_solicitado(
        self, cmd_id: str, ts: str, usuario: str, nombre: str, parametros: dict[str, str], seq: int
    ) -> None:
        parametros_json = json.dumps(parametros, ensure_ascii=False)
        with self._candado:
            self._conexion.execute(
                "INSERT INTO comando (cmd_id, ts, usuario, nombre, parametros, seq) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(cmd_id) DO UPDATE SET ts=excluded.ts, seq=excluded.seq",
                (cmd_id, ts, usuario, nombre, parametros_json, seq),
            )
            self._conexion.commit()

    def registrar_comando_resuelto(
        self, cmd_id: str, estado: str, causa: str | None, tardia: bool
    ) -> None:
        with self._candado:
            self._conexion.execute(
                "UPDATE comando SET estado = ?, causa = ?, tardia = ? WHERE cmd_id = ?",
                (estado, causa, 1 if tardia else 0, cmd_id),
            )
            self._conexion.commit()

    def ultimo_latido_ts(self) -> str | None:
        with self._candado:
            fila = self._conexion.execute(
                "SELECT ultimo_latido_ts FROM estado_enlace WHERE id = 1"
            ).fetchone()
        if fila is None:
            return None
        return None if fila[0] is None else str(fila[0])

    def actualizar_estado_enlace(
        self, enlace_estado: str, ultimo_latido_ts: str | None, actualizado_en: str
    ) -> None:
        with self._candado:
            self._conexion.execute(
                "UPDATE estado_enlace SET enlace_estado = ?, ultimo_latido_ts = ?, "
                "actualizado_en = ? WHERE id = 1",
                (enlace_estado, ultimo_latido_ts, actualizado_en),
            )
            self._conexion.commit()

    def registrar_latido(self, ts: str) -> None:
        """Guarda la marca del último latido para la AL01 retroactiva (A14)."""
        self.actualizar_estado_enlace("activo", ts, ts)

    def cantidad_eventos(self) -> int:
        with self._candado:
            fila = self._conexion.execute("SELECT COUNT(*) FROM evento").fetchone()
        return int(fila[0])

    def cantidad_telemetria(self) -> int:
        with self._candado:
            fila = self._conexion.execute("SELECT COUNT(*) FROM telemetria").fetchone()
        return int(fila[0])

    def comando_resuelto(self, cmd_id: str) -> tuple[str | None, str | None, int | None] | None:
        with self._candado:
            fila = self._conexion.execute(
                "SELECT estado, causa, seq FROM comando WHERE cmd_id = ?", (cmd_id,)
            ).fetchone()
        return None if fila is None else (fila[0], fila[1], fila[2])

    def estado_enlace_guardado(self) -> tuple[str, str | None]:
        with self._candado:
            fila = self._conexion.execute(
                "SELECT enlace_estado, ultimo_latido_ts FROM estado_enlace WHERE id = 1"
            ).fetchone()
        return fila[0], fila[1]
