"""Ciclo de vida de la cita (SPECS §11.2, A11; ROADMAP Etapa 11).

```
programada → cumplida   (el turno que la usó se cierra)
programada → vencida    (pasa fin + 5 min sin presentarse; tarea periódica)
programada → cancelada  (TERMINAL la cancela, o se anula el turno que la usó)
```

Una cita que ya respaldó el ingreso de un vehículo (``turno.cita_id``) no
vence mientras el turno sigue en la terminal: su desenlace lo decide el
turno (A11). El cumplimiento de ventana (``cumplida_en_ventana``) se fija al
presentarse en garita y la cita vencida lo registra en 0 (§11.1 regla 8).
"""

from dataclasses import dataclass

from web.repositorios.conexion_bd import ConexionBd
from web.repositorios.repositorio_citas import (
    COLUMNAS_CITA,
    SIN_TURNO_QUE_LA_USE,
    CitaConFranja,
    cita_de_fila,
)


@dataclass(frozen=True)
class CitaVencible:
    """Cita programada sin turno cuya ventana puede haber cerrado (§11.2)."""

    id: int
    transportista_id: int
    contenedor_id: str
    fecha: str
    inicio: str
    fin: str


@dataclass(frozen=True)
class VentanaRegistrada:
    """Franja de una cita con su cumplimiento de ventana ya registrado (§16.1 m7)."""

    fecha: str
    inicio: str
    cumplida_en_ventana: bool


class RepositorioCicloCita:
    """Transiciones de estado de la cita fuera de la agenda de TERMINAL."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def presentable_de_manifiesto(self, manifiesto_id: int, hoy: str) -> CitaConFranja | None:
        """La cita con la que el vehículo se presenta en garita (§9.4 paso 4).

        Primero la ``programada``. Si no hay, la ``vencida`` de hoy que ningún
        turno usó: llegar tarde es RT04, no un rechazo (§11.1 regla 7). Una
        vencida de otro día ya no sirve: hay que pedir otra cita [DEC].
        """
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_CITA} FROM cita JOIN franja "
                "ON cita.franja_fecha = franja.fecha AND cita.franja_inicio = franja.inicio "
                "WHERE cita.manifiesto_id = ? AND (cita.estado = 'programada' OR "
                f"(cita.estado = 'vencida' AND cita.franja_fecha = ? AND {SIN_TURNO_QUE_LA_USE})) "
                "ORDER BY cita.estado = 'programada' DESC, cita.id DESC LIMIT 1",
                (manifiesto_id, hoy),
            ).fetchone()
        return cita_de_fila(fila) if fila is not None else None

    def vencibles(self, hasta_fecha: str) -> list[CitaVencible]:
        """Programadas sin turno con franja hasta esa fecha local (candidatas a vencer)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT cita.id, cita.transportista_id, manifiesto.contenedor_id, "
                "cita.franja_fecha, cita.franja_inicio, franja.fin "
                "FROM cita JOIN manifiesto ON manifiesto.id = cita.manifiesto_id "
                "JOIN franja ON franja.fecha = cita.franja_fecha "
                "AND franja.inicio = cita.franja_inicio "
                "WHERE cita.estado = 'programada' AND cita.franja_fecha <= ? "
                f"AND {SIN_TURNO_QUE_LA_USE} "
                "ORDER BY cita.franja_fecha, cita.franja_inicio, cita.id",
                (hasta_fecha,),
            ).fetchall()
        return [
            CitaVencible(
                id=int(fila[0]),
                transportista_id=int(fila[1]),
                contenedor_id=str(fila[2]),
                fecha=str(fila[3]),
                inicio=str(fila[4]),
                fin=str(fila[5]),
            )
            for fila in filas
        ]

    def marcar_vencida(self, cita_id: int) -> bool:
        """``programada → vencida`` con ventana incumplida; False si ya cambió.

        La condición se repite en el UPDATE: si el vehículo entró en garita
        entre la lectura y la escritura, el turno ya la usa y no vence.
        """
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE cita SET estado = 'vencida', cumplida_en_ventana = 0 "
                f"WHERE id = ? AND estado = 'programada' AND {SIN_TURNO_QUE_LA_USE}",
                (cita_id,),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def cancelar_por_anulacion(self, cita_id: int) -> bool:
        """Turno anulado: su cita programada queda ``cancelada`` (A11 [DEC]).

        Conserva ``cumplida_en_ventana`` tal como se registró en garita: la
        métrica 7 sigue contando si llegó o no dentro de su ventana.
        """
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE cita SET estado = 'cancelada' WHERE id = ? AND estado = 'programada'",
                (cita_id,),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def en_uso(self, cita_id: int) -> bool:
        """True si un turno ya ingresó con esta cita."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT 1 FROM turno WHERE cita_id = ? LIMIT 1", (cita_id,)
            ).fetchone()
        return fila is not None

    def ventanas_registradas(self, desde_fecha: str, hasta_fecha: str) -> list[VentanaRegistrada]:
        """Citas con cumplimiento registrado cuyas franjas caen entre esas fechas locales."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT franja_fecha, franja_inicio, cumplida_en_ventana FROM cita "
                "WHERE cumplida_en_ventana IS NOT NULL "
                "AND franja_fecha >= ? AND franja_fecha <= ? ORDER BY franja_fecha, franja_inicio",
                (desde_fecha, hasta_fecha),
            ).fetchall()
        return [
            VentanaRegistrada(
                fecha=str(fila[0]), inicio=str(fila[1]), cumplida_en_ventana=bool(fila[2])
            )
            for fila in filas
        ]
