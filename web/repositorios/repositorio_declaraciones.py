"""Repositorio de declaraciones de mercancías (SPECS §9.3, §14.8, Etapa 7).

El AGENTE presenta la declaración sobre un manifiesto (número único, régimen,
descripción ≥ 10, valor > 0) y luego solicita el levante ante la AUTORIDAD.
"""

import sqlite3
from dataclasses import dataclass

from web.modelos.declaracion import Declaracion, Regimen
from web.repositorios.conexion_bd import ConexionBd, id_insertado

COLUMNAS_DECLARACION = (
    "id, manifiesto_id, agente_id, numero, regimen, descripcion, valor, presentada_en"
)


@dataclass(frozen=True)
class DeclaracionConManifiesto:
    """Declaración + identidad del manifiesto para la bandeja del AGENTE."""

    declaracion: Declaracion
    contenedor_id: str
    naviera: str
    peso_declarado_g: int
    estado_documental: str


class RepositorioDeclaraciones:
    """Ciclo documental del AGENTE (§9.1, §9.3)."""

    def __init__(self, bd: ConexionBd) -> None:
        self._bd = bd

    def crear(
        self,
        manifiesto_id: int,
        agente_id: int,
        numero: str,
        regimen: Regimen,
        descripcion: str,
        valor: int,
        presentada_en: str,
    ) -> tuple[bool, str | int]:
        """Crea la declaración; ``(False, causa)`` si falla (FK, CHECK o duplicado)."""
        with self._bd.candado:
            try:
                cursor = self._bd.conexion.execute(
                    "INSERT INTO declaracion (manifiesto_id, agente_id, numero, "
                    "regimen, descripcion, valor, presentada_en) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        manifiesto_id,
                        agente_id,
                        numero,
                        regimen.value,
                        descripcion,
                        valor,
                        presentada_en,
                    ),
                )
                self._bd.conexion.commit()
            except sqlite3.IntegrityError as error:
                msg = str(error).lower()
                if "unique" in msg:
                    return (False, "NUMERO_DUPLICADO")
                return (False, f"INTEGRIDAD: {error}")
        return (True, id_insertado(cursor))

    def de_manifiesto(self, manifiesto_id: int) -> Declaracion | None:
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_DECLARACION} FROM declaracion WHERE manifiesto_id = ?",
                (manifiesto_id,),
            ).fetchone()
        return _declaracion_de_fila(fila) if fila is not None else None

    def buscar_por_id(self, declaracion_id: int) -> Declaracion | None:
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_DECLARACION} FROM declaracion WHERE id = ?",
                (declaracion_id,),
            ).fetchone()
        return _declaracion_de_fila(fila) if fila is not None else None

    def buscar_por_numero(self, numero: str) -> Declaracion | None:
        with self._bd.candado:
            fila = self._bd.conexion.execute(
                f"SELECT {COLUMNAS_DECLARACION} FROM declaracion WHERE numero = ?",
                (numero,),
            ).fetchone()
        return _declaracion_de_fila(fila) if fila is not None else None


def _declaracion_de_fila(fila: sqlite3.Row) -> Declaracion:
    return Declaracion(
        id=int(fila[0]),
        manifiesto_id=int(fila[1]),
        agente_id=int(fila[2]),
        numero=str(fila[3]),
        regimen=Regimen(str(fila[4])),
        descripcion=str(fila[5]),
        valor=int(fila[6]),
        presentada_en=str(fila[7]),
    )
