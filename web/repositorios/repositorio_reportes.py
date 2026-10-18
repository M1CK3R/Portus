"""Repositorio de reportes de corrida (SPECS §16.3 [PROP], §17.1).

Cada reporte generado se persiste con su etiqueta, rango, política activa y
las 8 métricas en JSON, para poder recuperarlo y compararlo con la Fase 3.
También arma el detalle de cada turno del periodo para el CSV (§16.3).
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import cast

from web.modelos.reporte import Reporte
from web.repositorios.conexion_bd import ConexionBd, id_insertado

COLUMNAS_REPORTE = "id, etiqueta, inicio, fin, politica, resultado, generado_por, generado_en"


@dataclass(frozen=True)
class DetalleTurnoReporte:
    """Una fila del CSV del reporte: el turno con sus pesos, grúa y retenciones (§16.3)."""

    turno: int
    vehiculo: str
    transportista: str
    contenedor: str
    tipo_op: str
    estado: str
    canal: str
    dentro_de_ventana: bool | None
    peso_entrada_g: int | None
    peso_salida_g: int | None
    posicion_patio: str
    nivel: int | None
    ciclos_grua: int
    remociones: int
    distancia_grua: int
    retenciones: str
    """``RT01:CORREGIR RT03:abierta`` en orden de creación."""
    creado_en: str
    cerrado_en: str
    motivo_anulacion: str


class RepositorioReportes:
    """Alta y lectura de reportes persistidos (§16.3)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def registrar(
        self,
        etiqueta: str,
        inicio: str,
        fin: str,
        politica: str,
        resultado: dict[str, object],
        generado_por: int | None,
        generado_en: str,
    ) -> int:
        """Inserta el reporte y devuelve su id (§16.3)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT INTO reporte (etiqueta, inicio, fin, politica, resultado, "
                "generado_por, generado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    etiqueta,
                    inicio,
                    fin,
                    politica,
                    json.dumps(resultado, ensure_ascii=False),
                    generado_por,
                    generado_en,
                ),
            )
            self._bd.conexion.commit()
        return id_insertado(cursor)

    def recientes(self, limite: int) -> list[Reporte]:
        """Últimos reportes generados, del más nuevo al más viejo (§16.3 [PROP])."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_REPORTE} FROM reporte ORDER BY generado_en DESC, id DESC "
                "LIMIT ?",
                (limite,),
            ).fetchall()
        return [_reporte_de_fila(fila) for fila in filas]

    def detalle_de_turnos(self, inicio: str, fin: str) -> list[DetalleTurnoReporte]:
        """Turnos con actividad en el periodo: creados antes del fin y no cerrados antes del inicio.

        Un turno que empezó antes del rango y sigue o cierra dentro de él
        también es del periodo; las sumas de grúa cuentan sus ciclos completados.
        """
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT turno.id, vehiculo.identificador, usuario.nombre_mostrado, "
                "manifiesto.contenedor_id, turno.tipo_op, turno.estado, turno.canal, "
                "turno.dentro_de_ventana, turno.peso_entrada_g, turno.peso_salida_g, "
                "turno.posicion_patio, turno.nivel, "
                "(SELECT COUNT(*) FROM ciclo_grua WHERE ciclo_grua.turno_id = turno.id "
                "AND ciclo_grua.resultado = 'COMPLETADO'), "
                "(SELECT COUNT(*) FROM ciclo_grua WHERE ciclo_grua.turno_id = turno.id "
                "AND ciclo_grua.resultado = 'COMPLETADO' AND ciclo_grua.tipo = 'REMOCION'), "
                "(SELECT COALESCE(SUM(distancia_traslacion), 0) FROM ciclo_grua "
                "WHERE ciclo_grua.turno_id = turno.id), "
                "(SELECT GROUP_CONCAT(causa || ':' || COALESCE(resolucion, 'abierta'), ' ') "
                "FROM (SELECT causa, resolucion FROM retencion "
                "WHERE retencion.turno_id = turno.id ORDER BY retencion.id)), "
                "turno.creado_en, turno.cerrado_en, turno.motivo_anulacion "
                "FROM turno JOIN vehiculo ON turno.vehiculo_id = vehiculo.id "
                "JOIN manifiesto ON turno.manifiesto_id = manifiesto.id "
                "JOIN usuario ON usuario.id = manifiesto.transportista_id "
                "WHERE turno.creado_en <= ? "
                "AND (turno.cerrado_en IS NULL OR turno.cerrado_en >= ?) "
                "ORDER BY turno.id",
                (fin, inicio),
            ).fetchall()
        return [_detalle_de_fila(fila) for fila in filas]

    def buscar_por_id(self, reporte_id: int) -> Reporte | None:
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_REPORTE} FROM reporte WHERE id = ?",
                (reporte_id,),
            ).fetchone()
        return _reporte_de_fila(fila) if fila is not None else None


def _texto(valor: object) -> str:
    return "" if valor is None else str(valor)


def _entero_o_nulo(valor: object) -> int | None:
    return None if valor is None else int(str(valor))


def _detalle_de_fila(fila: sqlite3.Row) -> DetalleTurnoReporte:
    ventana = fila[7]
    return DetalleTurnoReporte(
        turno=int(fila[0]),
        vehiculo=str(fila[1]),
        transportista=str(fila[2]),
        contenedor=str(fila[3]),
        tipo_op=str(fila[4]),
        estado=str(fila[5]),
        canal=_texto(fila[6]),
        dentro_de_ventana=None if ventana is None else bool(ventana),
        peso_entrada_g=_entero_o_nulo(fila[8]),
        peso_salida_g=_entero_o_nulo(fila[9]),
        posicion_patio=_texto(fila[10]),
        nivel=_entero_o_nulo(fila[11]),
        ciclos_grua=int(fila[12]),
        remociones=int(fila[13]),
        distancia_grua=int(fila[14]),
        retenciones=_texto(fila[15]),
        creado_en=str(fila[16]),
        cerrado_en=_texto(fila[17]),
        motivo_anulacion=_texto(fila[18]),
    )


def _reporte_de_fila(fila: sqlite3.Row) -> Reporte:
    generado_por = fila[6]
    return Reporte(
        id=int(fila[0]),
        etiqueta=str(fila[1]),
        inicio=str(fila[2]),
        fin=str(fila[3]),
        politica=str(fila[4]),
        resultado=cast(dict[str, object], json.loads(str(fila[5]))),
        generado_por=None if generado_por is None else int(generado_por),
        generado_en=str(fila[7]),
    )
