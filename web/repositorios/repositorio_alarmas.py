"""Repositorio de alarmas del servidor (SPECS §13.2, §13.4)."""

import json
import sqlite3
from typing import cast

from web.modelos.alarma import Alarma
from web.repositorios.conexion_bd import ConexionBd, id_insertado


class RepositorioAlarmas:
    """Persiste alarmas hasta el reconocimiento (§13.2) con dedup §13.4 [DEC]."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def registrar(
        self,
        codigo: str,
        severidad: str,
        origen: str,
        descripcion: str,
        datos: dict[str, object],
        ts: str,
    ) -> int:
        """Crea la alarma o incrementa ``repeticiones`` si otra igual sigue activa (§13.4).

        La condición repetida no crea otra fila activa: la misma alarma de
        código y origen acumula repeticiones hasta que se reconozca.
        """
        with self._bd.candado:
            conexion = self._bd.conexion
            conexion.execute("BEGIN IMMEDIATE")
            try:
                activa = conexion.execute(
                    "SELECT id FROM alarma WHERE codigo = ? AND origen = ? AND estado = 'activa'",
                    (codigo, origen),
                ).fetchone()
                if activa is not None:
                    alarma_id = int(activa[0])
                    conexion.execute(
                        "UPDATE alarma SET repeticiones = repeticiones + 1, datos = ?, ts = ? "
                        "WHERE id = ?",
                        (json.dumps(datos, ensure_ascii=False), ts, alarma_id),
                    )
                else:
                    cursor = conexion.execute(
                        "INSERT INTO alarma (codigo, severidad, origen, descripcion, datos, ts) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            codigo,
                            severidad,
                            origen,
                            descripcion,
                            json.dumps(datos, ensure_ascii=False),
                            ts,
                        ),
                    )
                    alarma_id = id_insertado(cursor)
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise
        return alarma_id

    def activas(self, severidad: str | None = None) -> list[Alarma]:
        """Lista de alarmas activas; una no desaparece sola (§13.2).

        ``severidad`` filtra (§13.3: filtro por severidad); None lista todas.
        """
        return self._listar("WHERE alarma.estado = 'activa'", severidad=severidad)

    def historicas(self, severidad: str | None = None) -> list[Alarma]:
        return self._listar("WHERE alarma.estado = 'reconocida'", severidad=severidad)

    def reconocer(self, alarma_id: int, usuario_id: int, comentario: str | None, ts: str) -> bool:
        """Pasa una alarma activa a reconocida (§13.2); False si ya estaba o no existe."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE alarma SET estado = 'reconocida', reconocida_por = ?, "
                "reconocida_ts = ?, comentario = ? WHERE id = ? AND estado = 'activa'",
                (usuario_id, ts, comentario, alarma_id),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def reconocer_todas_baja_media(self, usuario_id: int, ts: str) -> int:
        """Reconoce todas las activas de severidad BAJA o MEDIA (§13.3).

        Las CRITICA y ALTA se reconocen una por una; esta operación las excluye.
        """
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE alarma SET estado = 'reconocida', reconocida_por = ?, "
                "reconocida_ts = ?, comentario = 'reconocida en lote' "
                "WHERE estado = 'activa' AND severidad IN ('BAJA', 'MEDIA')",
                (usuario_id, ts),
            )
            self._bd.conexion.commit()
        return cursor.rowcount

    def cantidad_activas(self) -> int:
        """Alarmas activas (filas, no repeticiones) para el contador del sinóptico (§14.1)."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT COUNT(*) FROM alarma WHERE estado = 'activa'"
            ).fetchone()
        return int(fila[0])

    def buscar_por_id(self, alarma_id: int) -> Alarma | None:
        filas = self._listar("WHERE alarma.id = ?", parametros=(alarma_id,))
        return filas[0] if filas else None

    def registrar_alerta(self, codigo: str, clave: str, alarma_id: int, ts: str) -> bool:
        """Marca que el objeto ``clave`` ya generó su AL12/AL13; False si ya lo había hecho."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT OR IGNORE INTO alerta_emitida (codigo, clave, alarma_id, ts) "
                "VALUES (?, ?, ?, ?)",
                (codigo, clave, alarma_id, ts),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def claves_alertadas(self, codigo: str) -> set[str]:
        """Objetos que ya generaron la alarma periódica ``codigo`` (AL12/AL13)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT clave FROM alerta_emitida WHERE codigo = ?", (codigo,)
            ).fetchall()
        return {str(fila[0]) for fila in filas}

    def fallas_de_grua(self) -> list[Alarma]:
        """Historial de fallas de la grúa (§12.6): AL03, AL04, AL05, AL06."""
        return self._listar("WHERE alarma.codigo IN ('AL03', 'AL04', 'AL05', 'AL06')")

    def _listar(
        self,
        condicion: str,
        severidad: str | None = None,
        parametros: tuple[object, ...] = (),
    ) -> list[Alarma]:
        if severidad is not None:
            condicion = f"{condicion} AND alarma.severidad = ?"
            parametros = (*parametros, severidad)
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT alarma.id, codigo, severidad, origen, descripcion, datos, "
                "repeticiones, estado, ts, reconocida_por, reconocida_ts, comentario, "
                "usuario.username FROM alarma "
                "LEFT JOIN usuario ON usuario.id = alarma.reconocida_por "
                f"{condicion} ORDER BY alarma.id DESC",
                parametros,
            ).fetchall()
        return [_alarma_de_fila(fila) for fila in filas]


def _alarma_de_fila(fila: sqlite3.Row) -> Alarma:
    reconocida_por = fila[9]
    return Alarma(
        id=int(fila[0]),
        codigo=str(fila[1]),
        severidad=str(fila[2]),
        origen=str(fila[3]),
        descripcion=str(fila[4]),
        datos=cast(dict[str, object], json.loads(str(fila[5]))),
        repeticiones=int(fila[6]),
        estado=str(fila[7]),
        ts=str(fila[8]),
        reconocida_por=None if reconocida_por is None else int(reconocida_por),
        reconocida_ts=cast(str | None, fila[10]),
        comentario=cast(str | None, fila[11]),
        reconocida_por_usuario=cast(str | None, fila[12]),
    )
