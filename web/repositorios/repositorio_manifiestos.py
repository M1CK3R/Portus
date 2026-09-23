"""Repositorio de manifiestos (SPECS §9.3, §17.1; filtros de propiedad §7.4).

En la Etapa 4 la tabla existía para los filtros de propiedad; la Etapa 5
agrega las lecturas que la validación de garita necesita (manifiesto vigente
del transportista, §9.4) y las escrituras del ciclo operativo: en_curso al
crear el turno, completado al cerrarlo, anulado al rechazar, y la corrección
de peso con historial (§10.3, A12).
"""

import sqlite3
from dataclasses import dataclass

from web.repositorios.conexion_bd import ConexionBd

COLUMNAS_MANIFIESTO = (
    "id, contenedor_id, naviera_id, transportista_id, tipo_op, "
    "peso_declarado_g, estado_documental, estado_operativo, creado_en"
)
COLUMNAS_VIGENTE = COLUMNAS_MANIFIESTO + ", tolerancia_pct"
"""Extensión para la validación de garita: la tolerancia queda en el índice 9."""


@dataclass(frozen=True)
class ResumenManifiesto:
    """Fila de listado; los estados viajan con los valores exactos de la BD."""

    id: int
    contenedor_id: str
    naviera_id: int
    transportista_id: int
    tipo_op: str
    peso_declarado_g: int
    estado_documental: str
    estado_operativo: str
    creado_en: str


@dataclass(frozen=True)
class ManifiestoVigente:
    """Manifiesto pendiente con sus datos de validación (§9.4)."""

    id: int
    contenedor_id: str
    naviera_id: int
    transportista_id: int
    tipo_op: str
    peso_declarado_g: int
    tolerancia_pct: int
    estado_documental: str
    estado_operativo: str = "sin_turno"


class RepositorioManifiestos:
    """Lecturas con filtro de propiedad y escrituras del ciclo operativo (A-2)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def listar(self, naviera_id: int | None = None) -> list[ResumenManifiesto]:
        """Lista manifiestos; si viene ``naviera_id`` filtra en SQL (§7.5.2).

        El rol NAVIERA pasa siempre su propio id (el de la sesión); los roles
        TERMINAL, AGENTE y AUTORIDAD lo dejan en None y ven el listado
        completo (§7.4, fila «Ver manifiesto completo»).
        """
        if naviera_id is None:
            sql = f"SELECT {COLUMNAS_MANIFIESTO} FROM manifiesto ORDER BY id"
            parametros: tuple[object, ...] = ()
        else:
            sql = f"SELECT {COLUMNAS_MANIFIESTO} FROM manifiesto WHERE naviera_id = ? ORDER BY id"
            parametros = (naviera_id,)
        with self._bd.candado:
            filas = self._bd.conexion.execute(sql, parametros).fetchall()
        return [_resumen_de_fila(fila) for fila in filas]

    def buscar_por_id(self, manifiesto_id: int) -> ManifiestoVigente | None:
        """Detalle completo del manifiesto para la lógica del turno."""
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_VIGENTE} FROM manifiesto WHERE id = ?",
                (manifiesto_id,),
            ).fetchone()
        if fila is None:
            return None
        return ManifiestoVigente(
            id=int(fila[0]),
            contenedor_id=str(fila[1]),
            naviera_id=int(fila[2]),
            transportista_id=int(fila[3]),
            tipo_op=str(fila[4]),
            peso_declarado_g=int(fila[5]),
            tolerancia_pct=int(fila[9]),
            estado_documental=str(fila[6]),
            estado_operativo=str(fila[7]),
        )

    def vigentes_de_transportista(self, transportista_id: int) -> list[ManifiestoVigente]:
        """Manifiestos con operación pendiente del transportista (§9.4 paso 2).

        «Vigente»: ``estado_operativo = 'sin_turno'``; el orden por id hace
        determinista la elección cuando hubiera más de uno [DEC, §9.4].
        """
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_VIGENTE} FROM manifiesto "
                "WHERE transportista_id = ? AND estado_operativo = 'sin_turno' "
                "ORDER BY id",
                (transportista_id,),
            ).fetchall()
        return [
            ManifiestoVigente(
                id=int(fila[0]),
                contenedor_id=str(fila[1]),
                naviera_id=int(fila[2]),
                transportista_id=int(fila[3]),
                tipo_op=str(fila[4]),
                peso_declarado_g=int(fila[5]),
                tolerancia_pct=int(fila[9]),
                estado_documental=str(fila[6]),
            )
            for fila in filas
        ]

    def marcar_operativo(self, manifiesto_id: int, estado_operativo: str) -> bool:
        """Mueve el estado operativo: sin_turno → en_curso → completado|anulado (§8.3)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE manifiesto SET estado_operativo = ? WHERE id = ?",
                (estado_operativo, manifiesto_id),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def corregir_peso(
        self,
        manifiesto_id: int,
        peso_medido_g: int,
        anterior_g: int,
        retencion_id: int,
        usuario_id: int,
        ts: str,
    ) -> None:
        """Corregir: sustituye el peso declarado por el medido y guarda el historial (§10.3).

        Ambas escrituras van en una transacción: sin fila de historial no hay
        corrección, y viceversa (BD-4).
        """
        with self._bd.candado:
            conexion = self._bd.conexion
            conexion.execute("BEGIN IMMEDIATE")
            try:
                cursor = conexion.execute(
                    "UPDATE manifiesto SET peso_declarado_g = ? WHERE id = ?",
                    (peso_medido_g, manifiesto_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError(f"el manifiesto {manifiesto_id} no existe")
                conexion.execute(
                    "INSERT INTO manifiesto_historial (manifiesto_id, campo, valor_anterior, "
                    "valor_nuevo, motivo, retencion_id, usuario_id, ts) "
                    "VALUES (?, 'peso_declarado_g', ?, ?, 'CORREGIR', ?, ?, ?)",
                    (
                        manifiesto_id,
                        str(anterior_g),
                        str(peso_medido_g),
                        retencion_id,
                        usuario_id,
                        ts,
                    ),
                )
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise

    def crear_demo(
        self,
        contenedor_id: str,
        naviera_id: int,
        transportista_id: int,
        tipo_op: str,
        peso_declarado_g: int,
        creado_en: str,
        tolerancia_pct: int = 5,
    ) -> bool:
        """Alta mínima para pruebas y demostración del aislamiento (P11).

        No es parte del flujo documental completo (los formularios de NAVIERA
        llegan en la Etapa 7): existe para poblar la bandeja desde las
        pruebas sin SQL suelto fuera de los repositorios (A-2).
        """
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "INSERT INTO manifiesto "
                "(contenedor_id, naviera_id, transportista_id, tipo_op, "
                " peso_declarado_g, tolerancia_pct, estado_documental, "
                " estado_operativo, creado_en) "
                "VALUES (?, ?, ?, ?, ?, ?, 'declarado', 'sin_turno', ?)",
                (
                    contenedor_id,
                    naviera_id,
                    transportista_id,
                    tipo_op,
                    peso_declarado_g,
                    tolerancia_pct,
                    creado_en,
                ),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0


def _resumen_de_fila(fila: sqlite3.Row) -> ResumenManifiesto:
    """Convierte la fila tipada en el modelo del dominio (PY-2)."""
    return ResumenManifiesto(
        id=int(fila[0]),
        contenedor_id=str(fila[1]),
        naviera_id=int(fila[2]),
        transportista_id=int(fila[3]),
        tipo_op=str(fila[4]),
        peso_declarado_g=int(fila[5]),
        estado_documental=str(fila[6]),
        estado_operativo=str(fila[7]),
        creado_en=str(fila[8]),
    )
