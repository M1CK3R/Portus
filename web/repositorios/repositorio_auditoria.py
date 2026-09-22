"""Auditoría de intentos rechazados (SPECS §7.5.5).

Cada rechazo de permisos y cada intento de inicio de sesión fallido queda
registrado con usuario, acción, recurso y momento; es la evidencia de la
prueba P10 y del escenario E12/R13.
"""

from dataclasses import dataclass

from web.repositorios.conexion_bd import ConexionBd


@dataclass(frozen=True)
class RechazoAuditado:
    """Una entrada de la bitácora de rechazos (§7.5.5)."""

    ts: str
    username: str | None
    rol: str | None
    accion: str
    recurso: str
    motivo: str


class RepositorioAuditoria:
    """Escritura y consulta de ``auditoria_rechazo``."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def registrar(
        self,
        accion: str,
        recurso: str,
        motivo: str,
        instante: str,
        username: str | None = None,
        rol: str | None = None,
    ) -> None:
        with self._bd.candado:
            self._bd.conexion.execute(
                "INSERT INTO auditoria_rechazo (ts, username, rol, accion, recurso, motivo) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (instante, username, rol, accion, recurso, motivo),
            )
            self._bd.conexion.commit()

    def contar(self) -> int:
        with self._bd.candado:
            fila = self._bd.conexion.execute("SELECT COUNT(*) FROM auditoria_rechazo").fetchone()
        return int(fila[0])

    def ultimos(self, cantidad: int) -> list[RechazoAuditado]:
        """Los rechazos más recientes; alimenta la revisión de E12/R13."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT ts, username, rol, accion, recurso, motivo FROM auditoria_rechazo "
                "ORDER BY id DESC LIMIT ?",
                (cantidad,),
            ).fetchall()
        return [
            RechazoAuditado(
                ts=str(fila[0]),
                username=None if fila[1] is None else str(fila[1]),
                rol=None if fila[2] is None else str(fila[2]),
                accion=str(fila[3]),
                recurso=str(fila[4]),
                motivo=str(fila[5]),
            )
            for fila in filas
        ]
