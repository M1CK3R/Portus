"""Repositorio de retenciones (SPECS §10, §17.3)."""

import sqlite3
from typing import cast

from web.modelos.retencion import CausaRetencion, Retencion
from web.repositorios.conexion_bd import ConexionBd, id_insertado

COLUMNAS_RETENCION = (
    "id, turno_id, causa, estacion, plaza, estado, peso_declarado_g, peso_medido_g, "
    "resolucion, motivo, observacion, resuelta_por, creada_en, resuelta_en"
)


class RepositorioRetenciones:
    """Ciclo de vida de la retención; una resuelta no vuelve a resolverse (§17.3)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def crear(
        self,
        turno_id: int,
        causa: CausaRetencion,
        estacion: str,
        plaza: int | None,
        peso_declarado_g: int | None,
        peso_medido_g: int | None,
        creada_en: str,
    ) -> int:
        """Abre la retención con su evidencia de peso cuando la causa lo amerita (§10.4)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT INTO retencion (turno_id, causa, estacion, plaza, estado, "
                "peso_declarado_g, peso_medido_g, creada_en) "
                "VALUES (?, ?, ?, ?, 'abierta', ?, ?, ?)",
                (
                    turno_id,
                    causa.value,
                    estacion,
                    plaza,
                    peso_declarado_g,
                    peso_medido_g,
                    creada_en,
                ),
            )
            self._bd.conexion.commit()
        return id_insertado(cursor)

    def buscar_por_id(self, retencion_id: int) -> Retencion | None:
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_RETENCION} FROM retencion WHERE id = ?", (retencion_id,)
            ).fetchone()
        return _retencion_de_fila(fila) if fila is not None else None

    def abierta_de_turno(self, turno_id: int) -> Retencion | None:
        """La retención abierta del turno retenido; None si está resuelta."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_RETENCION} FROM retencion "
                "WHERE turno_id = ? AND estado = 'abierta' ORDER BY id DESC LIMIT 1",
                (turno_id,),
            ).fetchone()
        return _retencion_de_fila(fila) if fila is not None else None

    def tiene_causa(self, turno_id: int, causa: CausaRetencion) -> bool:
        """True si el turno ya tuvo (abierta o resuelta) una retención de esa causa."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                "SELECT 1 FROM retencion WHERE turno_id = ? AND causa = ? LIMIT 1",
                (turno_id, causa.value),
            ).fetchone()
        return fila is not None

    def resolver(
        self,
        retencion_id: int,
        resolucion: str,
        motivo: str | None,
        observacion: str | None,
        resuelta_por: int,
        resuelta_en: str,
    ) -> bool:
        """Cierra la retención solo si sigue abierta (§17.3: CHECK en el UPDATE)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE retencion SET estado = 'resuelta', resolucion = ?, motivo = ?, "
                "observacion = ?, resuelta_por = ?, resuelta_en = ? "
                "WHERE id = ? AND estado = 'abierta'",
                (resolucion, motivo, observacion, resuelta_por, resuelta_en, retencion_id),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def listar(
        self,
        estado: str | None = None,
        solo_aduaneras: bool = False,
        causa: str | None = None,
    ) -> list[Retencion]:
        """Bandeja §14.3: abiertas/resueltas; AUTORIDAD ve solo aduaneras (§7.4).

        ``causa`` filtra (RT01-RT06); ``estado`` filtra abierta/resuelta.
        """
        sql = f"SELECT {COLUMNAS_RETENCION} FROM retencion"
        condiciones: list[str] = []
        parametros: list[object] = []
        if estado is not None:
            condiciones.append("estado = ?")
            parametros.append(estado)
        if solo_aduaneras:
            condiciones.append("causa IN ('RT03', 'RT05')")
        if causa is not None:
            condiciones.append("causa = ?")
            parametros.append(causa)
        if condiciones:
            sql += " WHERE " + " AND ".join(condiciones)
        sql += " ORDER BY id DESC"
        with self._bd.candado:
            filas = self._bd.conexion.execute(sql, tuple(parametros)).fetchall()
        return [_retencion_de_fila(fila) for fila in filas]

    def listar_bandeja(
        self,
        estado: str | None = None,
        solo_aduaneras: bool = False,
        causa: str | None = None,
    ) -> list[tuple[Retencion, str, str, str]]:
        """(retención, vehículo, contenedor, tipo_op) para la bandeja §14.3.

        Admite los mismos filtros que ``listar``.
        """
        columnas = ", ".join(f"retencion.{c}" for c in COLUMNAS_RETENCION.split(", "))
        sql = (
            f"SELECT {columnas}, vehiculo.identificador, manifiesto.contenedor_id, turno.tipo_op "
            "FROM retencion JOIN turno ON retencion.turno_id = turno.id "
            "JOIN vehiculo ON turno.vehiculo_id = vehiculo.id "
            "JOIN manifiesto ON turno.manifiesto_id = manifiesto.id"
        )
        condiciones: list[str] = []
        parametros: list[object] = []
        if estado is not None:
            condiciones.append("retencion.estado = ?")
            parametros.append(estado)
        if solo_aduaneras:
            condiciones.append("retencion.causa IN ('RT03', 'RT05')")
        if causa is not None:
            condiciones.append("retencion.causa = ?")
            parametros.append(causa)
        if condiciones:
            sql += " WHERE " + " AND ".join(condiciones)
        sql += " ORDER BY retencion.id DESC"
        with self._bd.candado:
            filas = self._bd.conexion.execute(sql, tuple(parametros)).fetchall()
        return [
            (_retencion_de_fila(fila), str(fila[14]), str(fila[15]), str(fila[16]))
            for fila in filas
        ]

    def abiertas_sin_alerta(self, creadas_hasta: str) -> list[Retencion]:
        """Abiertas creadas en o antes de ``creadas_hasta`` que aún no generaron AL12 (§13.1)."""
        columnas = ", ".join(f"retencion.{c}" for c in COLUMNAS_RETENCION.split(", "))
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                f"SELECT {columnas} FROM retencion "
                "LEFT JOIN alerta_emitida ON alerta_emitida.codigo = 'AL12' "
                "AND alerta_emitida.clave = CAST(retencion.id AS TEXT) "
                "WHERE retencion.estado = 'abierta' AND retencion.creada_en <= ? "
                "AND alerta_emitida.clave IS NULL ORDER BY retencion.id",
                (creadas_hasta,),
            ).fetchall()
        return [_retencion_de_fila(fila) for fila in filas]

    def resueltas_en_rango(self, inicio: str, fin: str) -> list[tuple[str, str, str, str]]:
        """(causa, resolucion, creada_en, resuelta_en) para la métrica 5 y 8 (§16.1)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT causa, resolucion, creada_en, resuelta_en FROM retencion "
                "WHERE estado = 'resuelta' AND resuelta_en >= ? AND resuelta_en <= ? "
                "ORDER BY resuelta_en",
                (inicio, fin),
            ).fetchall()
        return [
            (str(f[0]), str(f[1]) if f[1] is not None else "", str(f[2]), str(f[3])) for f in filas
        ]


def _retencion_de_fila(fila: sqlite3.Row) -> Retencion:
    return Retencion(
        id=int(fila[0]),
        turno_id=int(fila[1]),
        causa=CausaRetencion(str(fila[2])),
        estacion=str(fila[3]),
        plaza=cast(int | None, fila[4]),
        estado=str(fila[5]),
        peso_declarado_g=cast(int | None, fila[6]),
        peso_medido_g=cast(int | None, fila[7]),
        resolucion=cast(str | None, fila[8]),
        motivo=cast(str | None, fila[9]),
        observacion=cast(str | None, fila[10]),
        resuelta_por=cast(int | None, fila[11]),
        creada_en=str(fila[12]),
        resuelta_en=cast(str | None, fila[13]),
    )
