"""Repositorio de manifiestos (SPECS §9.3, §17.1; filtros de propiedad §7.4).

En la Etapa 4 la tabla existía para los filtros de propiedad; la Etapa 5
agrega las lecturas que la validación de garita necesita (manifiesto vigente
del transportista, §9.4) y las escrituras del ciclo operativo: en_curso al
crear el turno, completado al cerrarlo, anulado al rechazar, y la corrección
de peso con historial (§10.3, A12).
"""

import sqlite3
from dataclasses import dataclass

from web.repositorios.conexion_bd import ConexionBd, id_insertado

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


@dataclass(frozen=True)
class DetalleManifiesto:
    """Detalle del manifiesto con su historial de cambios (§14.7)."""

    manifiesto: ManifiestoVigente
    historial: list["FilaHistorial"]


@dataclass(frozen=True)
class FilaHistorial:
    """Una entrada del historial del manifiesto (§10.3 Corregir, §14.7)."""

    id: int
    campo: str
    valor_anterior: str
    valor_nuevo: str
    motivo: str
    ts: str


@dataclass(frozen=True)
class ContenedorPropio:
    """Contenedor de una naviera con ubicación, estado y permanencia (§14.7)."""

    contenedor_id: str
    posicion: str
    nivel: int
    estado_operativo: str
    autorizacion: str
    ingreso_en: str
    remociones: int


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

    def buscar_por_id(
        self, manifiesto_id: int, naviera_id: int | None = None
    ) -> ManifiestoVigente | None:
        """Detalle completo del manifiesto; con ``naviera_id`` filtra en SQL (§7.5.2)."""
        sql = f"SELECT {COLUMNAS_VIGENTE} FROM manifiesto WHERE id = ?"
        parametros: tuple[object, ...] = (manifiesto_id,)
        if naviera_id is not None:
            sql += " AND naviera_id = ?"
            parametros = (manifiesto_id, naviera_id)
        with self._bd.candado:
            fila = self._bd.conexion.execute(sql, parametros).fetchone()
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

    # ----------------------------------------------- Etapa 7 · NAVIERA §14.7

    def crear(
        self,
        naviera_id: int,
        contenedor_id: str,
        tipo_op: str,
        peso_declarado_g: int,
        tolerancia_pct: int,
        transportista_id: int,
        observaciones: str,
        creado_en: str,
    ) -> tuple[bool, str | int]:
        """Alta de manifiesto por NAVIERA con validaciones (§9.3, §14.7).

        Devuelve ``(True, manifiesto_id)`` o ``(False, causa)`` donde causa es
        ``CONTENEDOR_INEXISTENTE``, ``TRANSPORTISTA_INEXISTENTE`` o
        ``CONTENEDOR_CON_PENDIENTE``. La regla "un
        contenedor no puede tener dos manifiestos pendientes" la garantiza el
        ``UNIQUE`` de ``ix_manifiesto_pendiente_por_contenedor`` (§9.3).
        """
        with self._bd.candado:
            conexion = self._bd.conexion
            try:
                existe = conexion.execute(
                    "SELECT 1 FROM contenedor WHERE id = ?", (contenedor_id,)
                ).fetchone()
                if existe is None:
                    return (False, "CONTENEDOR_INEXISTENTE")
                # Sin esta validación un id inexistente llega al INSERT y
                # la BD responde con un FOREIGN KEY constraint failed opaco.
                transportista = conexion.execute(
                    "SELECT 1 FROM usuario WHERE id = ? AND rol = 'TRANSPORTISTA' AND activo = 1",
                    (transportista_id,),
                ).fetchone()
                if transportista is None:
                    return (False, "TRANSPORTISTA_INEXISTENTE")
                pendiente = conexion.execute(
                    "SELECT 1 FROM manifiesto WHERE contenedor_id = ? "
                    "AND estado_operativo = 'sin_turno'",
                    (contenedor_id,),
                ).fetchone()
                if pendiente is not None:
                    return (False, "CONTENEDOR_CON_PENDIENTE")
                cursor = conexion.execute(
                    "INSERT INTO manifiesto (contenedor_id, naviera_id, transportista_id, "
                    "tipo_op, peso_declarado_g, tolerancia_pct, estado_documental, "
                    "estado_operativo, observaciones, creado_en) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'declarado', 'sin_turno', ?, ?)",
                    (
                        contenedor_id,
                        naviera_id,
                        transportista_id,
                        tipo_op,
                        peso_declarado_g,
                        tolerancia_pct,
                        observaciones,
                        creado_en,
                    ),
                )
                conexion.commit()
                return (True, id_insertado(cursor))
            except sqlite3.IntegrityError as error:
                conexion.rollback()
                return (False, f"FK_VIOLATION: {error}")
            except Exception:
                conexion.rollback()
                raise

    def anular(self, manifiesto_id: int, naviera_id: int) -> bool:
        """Anula un manifiesto solo si no tiene turno (estado_operativo='sin_turno').

        Filtro de propiedad: la naviera solo anula los suyos (§7.5.2).
        """
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE manifiesto SET estado_documental = 'anulado', "
                "estado_operativo = 'anulado' "
                "WHERE id = ? AND naviera_id = ? AND estado_operativo = 'sin_turno'",
                (manifiesto_id, naviera_id),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def detalle_con_historial(
        self, manifiesto_id: int, naviera_id: int | None = None
    ) -> DetalleManifiesto | None:
        """Detalle del manifiesto + historial (§14.7, §10.3); ajeno a la naviera → None."""
        manifiesto = self.buscar_por_id(manifiesto_id, naviera_id)
        if manifiesto is None:
            return None
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT id, campo, valor_anterior, valor_nuevo, motivo, ts "
                "FROM manifiesto_historial WHERE manifiesto_id = ? ORDER BY id",
                (manifiesto_id,),
            ).fetchall()
        historial = [
            FilaHistorial(
                id=int(f[0]),
                campo=str(f[1]),
                valor_anterior=str(f[2]),
                valor_nuevo=str(f[3]),
                motivo=str(f[4]),
                ts=str(f[5]),
            )
            for f in filas
        ]
        return DetalleManifiesto(manifiesto=manifiesto, historial=historial)

    def mis_contenedores(self, naviera_id: int) -> list[ContenedorPropio]:
        """Contenedores de la naviera con ubicación, estado y autorización (§14.7)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                "SELECT inventario.contenedor_id, inventario.posicion, inventario.nivel, "
                "manifiesto.estado_operativo, inventario.autorizacion, "
                "inventario.ingreso_en, inventario.remociones "
                "FROM inventario JOIN manifiesto ON manifiesto.contenedor_id = "
                "inventario.contenedor_id WHERE manifiesto.naviera_id = ? "
                "ORDER BY inventario.ingreso_en",
                (naviera_id,),
            ).fetchall()
        return [
            ContenedorPropio(
                contenedor_id=str(f[0]),
                posicion=str(f[1]),
                nivel=int(f[2]),
                estado_operativo=str(f[3]),
                autorizacion=str(f[4]),
                ingreso_en=str(f[5]),
                remociones=int(f[6]),
            )
            for f in filas
        ]

    def sin_levante(self) -> list[ManifiestoVigente]:
        """Manifiestos sin levante para la bandeja del AGENTE (§14.8)."""
        with self._bd.candado:
            filas = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_VIGENTE} FROM manifiesto "
                "WHERE estado_documental IN ('declarado', 'declaracion_presentada') "
                "AND estado_operativo = 'sin_turno' ORDER BY id"
            ).fetchall()
        return [self._vigente_de_fila(f) for f in filas]

    def marcar_documental(self, manifiesto_id: int, estado_documental: str) -> bool:
        """Mueve el estado documental (declaracion_presentada / levante_solicitado / etc.)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE manifiesto SET estado_documental = ? WHERE id = ?",
                (estado_documental, manifiesto_id),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    def adjuntar_observacion(self, manifiesto_id: int, observacion: str) -> bool:
        """Nota documental del AGENTE visible para la AUTORIDAD (§14.8)."""
        with self._bd.candado:
            cursor = self._bd.conexion.execute(
                "UPDATE manifiesto SET observaciones = ? WHERE id = ?",
                (observacion, manifiesto_id),
            )
            self._bd.conexion.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _vigente_de_fila(fila: sqlite3.Row) -> ManifiestoVigente:
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
