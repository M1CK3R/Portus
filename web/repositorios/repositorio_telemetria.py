"""Repositorio de telemetría del lado web (SPECS §17.1 ``telemetría``).

La tabla ya existía para el puente (Etapa 3); la lógica del servidor escribe
aquí su bitácora de reconciliación (§3.3): cada vez que el enlace se
restablece o arranca el servicio, se registra el resumen de eventos aplicados
y duplicados.
"""

import uuid

from web.repositorios.conexion_bd import ConexionBd


class RepositorioTelemetria:
    """Filas de telemetría generadas por la lógica (id determinista por contenido)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def registrar(self, id_unico: str, ts: str, tipo: str, valor: str) -> None:
        """Alta idempotente: el mismo resumen no se registra dos veces."""
        with self._bd.candado:
            self._bd.conexion.execute(
                "INSERT OR IGNORE INTO telemetria (id, ts, tipo, valor) VALUES (?, ?, ?, ?)",
                (id_unico, ts, tipo, valor),
            )
            self._bd.conexion.commit()

    def max_fila_espera_en_rango(self, inicio: str, fin: str) -> int:
        """Longitud máxima de la fila de espera en el rango (§16.1 métrica 6).

        La telemetría de la fila de espera la escribe la lógica con
        ``tipo='fila_espera'`` y el entero en ``valor``; sin muestras devuelve 0.
        """
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT MAX(CAST(valor AS INTEGER)) FROM telemetria "
                "WHERE tipo = 'fila_espera' AND ts >= ? AND ts <= ?",
                (inicio, fin),
            ).fetchone()
        return 0 if fila[0] is None else int(fila[0])

    def registrar_fila_espera(self, cantidad: int, ts: str) -> None:
        """Deja una muestra de la longitud de la fila de espera (§16.1 m6).

        Idempotente por contenido (uuid5) para no duplicar la misma muestra.
        """
        id_unico = str(uuid.uuid5(uuid.NAMESPACE_URL, f"fila_espera:{ts}:{cantidad}"))
        self.registrar(id_unico, ts, "fila_espera", str(cantidad))
