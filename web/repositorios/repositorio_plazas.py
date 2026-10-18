"""Repositorio de las 3 plazas del parqueo de retención (SPECS §10.1, §10.6).

La asignación y la liberación corren dentro de una transacción con bloqueo
(``BEGIN IMMEDIATE``, P08): dos retenciones casi simultáneas no obtienen la
misma plaza, porque la consulta de la plaza libre y el UPDATE que la toma se
ejecutan bajo el mismo bloqueo de la base y del candado del proceso (§10.6).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from web.repositorios.conexion_bd import ConexionBd


@dataclass(frozen=True)
class Plaza:
    """Una plaza lógica del ramal; ``turno_id`` distingue libre de ocupada."""

    numero: int
    turno_id: int | None
    ocupada_desde: str | None


class ErrorPlaza(Exception):
    """No hay plaza libre en el momento de asignar (§10.1 paso 6 → AL11)."""


class RepositorioPlazas:
    """Administración lógica de las plazas 1-3 con exclusión mutua (P08)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def asignar(self, turno_id: int, ocupada_desde: str) -> int:
        """Toma la plaza libre de menor número para el turno (§10.1 paso 1).

        Lanza :class:`ErrorPlaza` si las tres están ocupadas; el servicio lo
        convierte en el rechazo PARQUEO_LLENO con AL11 (§9.4) o en la
        retención sin ramal (A3 [DEC]) según el punto donde nace.
        """
        with self._bd.candado:
            conexion = self._bd.conexion
            # BEGIN IMMEDIATE fija el bloqueo de escritura antes de consultar:
            # ningún otro escritor puede tomar la plaza entre SELECT y UPDATE.
            conexion.execute("BEGIN IMMEDIATE")
            try:
                fila = conexion.execute(
                    "SELECT numero FROM plaza_parqueo "
                    "WHERE turno_id IS NULL ORDER BY numero LIMIT 1"
                ).fetchone()
                if fila is None:
                    raise ErrorPlaza("las 3 plazas del parqueo están ocupadas")
                numero = int(fila[0])
                cursor = conexion.execute(
                    "UPDATE plaza_parqueo SET turno_id = ?, ocupada_desde = ? "
                    "WHERE numero = ? AND turno_id IS NULL",
                    (turno_id, ocupada_desde, numero),
                )
                if cursor.rowcount != 1:  # defensa: no debería ocurrir bajo IMMEDIATE
                    raise ErrorPlaza(f"la plaza {numero} dejó de estar libre al asignar")
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise
        return numero

    def liberar(self, numero: int) -> float:
        """Libera la plaza y devuelve los segundos que estuvo ocupada (§10.6)."""
        with self._bd.candado:
            conexion = self._bd.conexion
            conexion.execute("BEGIN IMMEDIATE")
            try:
                fila = conexion.execute(
                    "SELECT turno_id, ocupada_desde FROM plaza_parqueo WHERE numero = ?",
                    (numero,),
                ).fetchone()
                if fila is None:
                    raise ValueError(f"la plaza {numero} no existe")
                conexion.execute(
                    "UPDATE plaza_parqueo SET turno_id = NULL, ocupada_desde = NULL "
                    "WHERE numero = ?",
                    (numero,),
                )
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise
            desde = fila[1]
        return _segundos_desde(desde)

    def todas(self) -> list[Plaza]:
        """Estado completo del parqueo para el sinóptico (§14.1)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT numero, turno_id, ocupada_desde FROM plaza_parqueo ORDER BY numero"
            ).fetchall()
        return [
            Plaza(
                numero=int(fila[0]),
                turno_id=None if fila[1] is None else int(fila[1]),
                ocupada_desde=None if fila[2] is None else str(fila[2]),
            )
            for fila in filas
        ]

    def hay_libre(self) -> bool:
        """True si al menos una plaza está libre (§9.4, riesgo de retención)."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT 1 FROM plaza_parqueo WHERE turno_id IS NULL LIMIT 1"
            ).fetchone()
        return fila is not None

    def de_turno(self, turno_id: int) -> Plaza | None:
        """La plaza que ocupa el turno, si la tiene (retenciones tardías, A3)."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT numero, turno_id, ocupada_desde FROM plaza_parqueo "
                "WHERE turno_id = ? ORDER BY numero LIMIT 1",
                (turno_id,),
            ).fetchone()
        if fila is None:
            return None
        return Plaza(
            numero=int(fila[0]),
            turno_id=turno_id,
            ocupada_desde=None if fila[2] is None else str(fila[2]),
        )


def _segundos_desde(ocupada_desde: str | None) -> float:
    """Duración de la ocupación en segundos; 0.0 si la marca no existe."""
    if not ocupada_desde:
        return 0.0
    desde = datetime.fromisoformat(ocupada_desde)
    if desde.tzinfo is None:
        desde = desde.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - desde).total_seconds())
