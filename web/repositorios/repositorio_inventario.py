"""Repositorio del patio: posiciones e inventario (SPECS §12.1-§12.3, §17.1).

El inventario cambia **solo** con confirmación física del controlador
(``PAT``/``GRU`` confirmados, §12.3): los métodos de escritura se invocan
exclusivamente desde el consumo de esos eventos, nunca al emitir un comando
(§8.2 regla 2). Las escrituras van en transacción (BD-4).
"""

import sqlite3
from dataclasses import dataclass

from web.modelos.patio import CeldaInventario, EstadoDePosicion
from web.repositorios.conexion_bd import ConexionBd


@dataclass(frozen=True)
class FilaInventario:
    """Fila del inventario por contenedor (SPECS §12.2: 8 campos)."""

    contenedor_id: str
    naviera: str
    posicion: str
    nivel: int
    peso_declarado_g: int
    autorizacion: str
    ingreso_en: str
    remociones: int


class RepositorioInventario:
    """Posiciones del patio y ubicación confirmada de cada contenedor."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    # ------------------------------------------------------------- lecturas

    def celdas(self) -> list[CeldaInventario]:
        """Todas las celdas (posición, nivel) con su contenedor, si hay (§12.2)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT p.id, n.nivel, i.contenedor_id, i.remociones, i.ingreso_en "
                "FROM posicion_patio p "
                "CROSS JOIN (SELECT 1 AS nivel UNION SELECT 2) n "
                "LEFT JOIN inventario i ON i.posicion = p.id AND i.nivel = n.nivel "
                "ORDER BY p.id, n.nivel"
            ).fetchall()
        return [
            CeldaInventario(
                posicion=str(fila[0]),
                nivel=int(fila[1]),
                contenedor_id=None if fila[2] is None else str(fila[2]),
                remociones=int(fila[3] or 0),
                ingreso_en=None if fila[4] is None else str(fila[4]),
            )
            for fila in filas
        ]

    def posicion(self, posicion_id: str) -> EstadoDePosicion | None:
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT id, estado FROM posicion_patio WHERE id = ?", (posicion_id,)
            ).fetchone()
        return EstadoDePosicion(id=str(fila[0]), estado=str(fila[1])) if fila is not None else None

    def posiciones(self) -> list[EstadoDePosicion]:
        """Todas las posiciones con su estado base, en orden (§12.1)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT id, estado FROM posicion_patio ORDER BY id"
            ).fetchall()
        return [EstadoDePosicion(id=str(fila[0]), estado=str(fila[1])) for fila in filas]

    def celda_de_contenedor(self, contenedor_id: str) -> CeldaInventario | None:
        """Ubicación confirmada del contenedor; None si no está en el patio."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT posicion, nivel, contenedor_id, remociones, ingreso_en "
                "FROM inventario WHERE contenedor_id = ?",
                (contenedor_id,),
            ).fetchone()
        if fila is None:
            return None
        return CeldaInventario(
            posicion=str(fila[0]),
            nivel=int(fila[1]),
            contenedor_id=contenedor_id,
            remociones=int(fila[3] or 0),
            ingreso_en=None if fila[4] is None else str(fila[4]),
        )

    def inventario_completo(self) -> list[FilaInventario]:
        """Inventario por contenedor con los 8 campos de §12.2 para la pestaña Patio.

        El ``peso_declarado_g`` viene del manifiesto vigente del contenedor y la
        ``naviera`` es el ``nombre_mostrado`` del usuario naviera. Ordenado por
        permanencia descendente (§12.2: ordenamiento por permanencia).
        """
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT inventario.contenedor_id, usuario.nombre_mostrado, "
                "inventario.posicion, inventario.nivel, "
                "manifiesto.peso_declarado_g, inventario.autorizacion, "
                "inventario.ingreso_en, inventario.remociones "
                "FROM inventario JOIN manifiesto ON manifiesto.contenedor_id = "
                "inventario.contenedor_id JOIN usuario ON usuario.id = manifiesto.naviera_id "
                "WHERE manifiesto.estado_operativo IN ('en_curso', 'completado') "
                "ORDER BY inventario.ingreso_en ASC"
            ).fetchall()
        return [
            FilaInventario(
                contenedor_id=str(f[0]),
                naviera=str(f[1]),
                posicion=str(f[2]),
                nivel=int(f[3]),
                peso_declarado_g=int(f[4]),
                autorizacion=str(f[5]),
                ingreso_en=str(f[6]),
                remociones=int(f[7]),
            )
            for f in filas
        ]

    def crear_posicion(self, posicion_id: str) -> None:
        """Alta de catálogo para la semilla (§19.3)."""
        with self._bd.candado:
            self._bd.conexion.execute(
                "INSERT OR IGNORE INTO posicion_patio (id, estado) VALUES (?, 'libre')",
                (posicion_id,),
            )
            self._bd.conexion.commit()

    # ------------------------------------------------------------ escrituras

    def reservar(self, posicion_id: str) -> None:
        """Marca la posición como ``reservada`` al asignarla (§12.3: solo pasa a
        ocupada con la confirmación física del controlador).

        Una posición ``ocupada`` también se reserva: la política asigna el
        nivel 2 sobre un nivel 1 ocupado (apilado, §12.1). Reservada o
        bloqueada no, para que dos turnos no reciban la misma celda.
        """
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE posicion_patio SET estado = 'reservada' "
                "WHERE id = ? AND estado IN ('libre', 'ocupada')",
                (posicion_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"la posición '{posicion_id}' no está libre para reservar")
            self._bd.conexion.commit()

    def liberar_reserva(self, posicion_id: str) -> str | None:
        """Deshace la reserva de un trabajo cancelado; devuelve el estado nuevo (§12.3).

        La posición vuelve a lo que el inventario confirmado dice: ``ocupada``
        si aún tiene contenedores, ``libre`` si no. None si no estaba reservada.
        """
        with self._bd.candado:
            conexion = self._bd.conexion
            conexion.execute("BEGIN IMMEDIATE")
            try:
                ocupantes = conexion.execute(
                    "SELECT COUNT(*) FROM inventario WHERE posicion = ?", (posicion_id,)
                ).fetchone()[0]
                estado = "ocupada" if int(ocupantes) > 0 else "libre"
                cursor = conexion.execute(
                    "UPDATE posicion_patio SET estado = ? WHERE id = ? AND estado = 'reservada'",
                    (estado, posicion_id),
                )
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise
        return estado if cursor.rowcount == 1 else None

    def confirmar_ocupacion(
        self, contenedor_id: str, posicion_id: str, nivel: int, ingreso_en: str
    ) -> None:
        """PAT confirmado: contenedor en la celda y posición ocupada (§12.3)."""
        with self._bd.candado:
            conexion = self._bd.conexion
            conexion.execute("BEGIN IMMEDIATE")
            try:
                previa = conexion.execute(
                    "SELECT posicion, nivel FROM inventario WHERE contenedor_id = ?",
                    (contenedor_id,),
                ).fetchone()
                if previa is not None and (str(previa[0]), int(previa[1])) != (posicion_id, nivel):
                    _liberar_celda(conexion, str(previa[0]), int(previa[1]))
                conexion.execute(
                    "INSERT INTO inventario "
                    "(contenedor_id, posicion, nivel, ingreso_en, remociones, autorizacion) "
                    "VALUES (?, ?, ?, ?, COALESCE( "
                    "(SELECT remociones FROM inventario WHERE contenedor_id = ?), 0), "
                    "'LEVANTE_OTORGADO') "
                    "ON CONFLICT (contenedor_id) DO UPDATE SET posicion = excluded.posicion, "
                    "nivel = excluded.nivel, ingreso_en = excluded.ingreso_en",
                    (contenedor_id, posicion_id, nivel, ingreso_en, contenedor_id),
                )
                # La confirmación física manda (§12.3): pasa a ocupada aunque
                # la reserva se perdiera (reconciliación, PAT no planeado).
                conexion.execute(
                    "UPDATE posicion_patio SET estado = 'ocupada' "
                    "WHERE id = ? AND estado IN ('libre', 'reservada')",
                    (posicion_id,),
                )
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise

    def confirmar_retiro(self, contenedor_id: str, posicion_id: str, nivel: int) -> None:
        """PAT confirmado de salida: la celda queda libre y el contenedor sale del inventario."""
        with self._bd.candado:
            conexion = self._bd.conexion
            conexion.execute("BEGIN IMMEDIATE")
            try:
                _liberar_celda(conexion, posicion_id, nivel)
                conexion.execute(
                    "DELETE FROM inventario WHERE contenedor_id = ? AND posicion = ? AND nivel = ?",
                    (contenedor_id, posicion_id, nivel),
                )
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise

    def incrementar_remociones(self, contenedor_id: str) -> None:
        """Cuenta la remoción confirmada de un contenedor (§8.2 regla 2, §12.5)."""
        with self._bd.candado:
            self._bd.conexion.execute(
                "UPDATE inventario SET remociones = remociones + 1 WHERE contenedor_id = ?",
                (contenedor_id,),
            )
            self._bd.conexion.commit()

    def bloquear(self, posicion_id: str) -> bool:
        """Bloquea una posición (§12.2); rechaza si está ocupada o reservada."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE posicion_patio SET estado = 'bloqueada' WHERE id = ? AND estado = 'libre'",
                (posicion_id,),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def desbloquear(self, posicion_id: str) -> bool:
        """Libera el bloqueo: solo aplica a posiciones bloqueadas (§12.2)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE posicion_patio SET estado = 'libre' WHERE id = ? AND estado = 'bloqueada'",
                (posicion_id,),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0


def _liberar_celda(conexion: sqlite3.Connection, posicion_id: str, nivel: int) -> None:
    """Deja la celda anterior libre y evalúa el estado agregado de la posición."""
    conexion.execute(
        "DELETE FROM inventario WHERE posicion = ? AND nivel = ?", (posicion_id, nivel)
    )
    ocupantes = conexion.execute(
        "SELECT COUNT(*) FROM inventario WHERE posicion = ?", (posicion_id,)
    ).fetchone()[0]
    if int(ocupantes) == 0:
        conexion.execute(
            "UPDATE posicion_patio SET estado = 'libre' WHERE id = ? AND estado = 'ocupada'",
            (posicion_id,),
        )
