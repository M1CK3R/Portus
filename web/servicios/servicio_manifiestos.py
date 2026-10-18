"""NAVIERA: manifiestos y contenedores propios (SPECS §14.7, §9.3, Etapa 7).

Crear manifiesto con validaciones (contenedor existente, sin dos pendientes),
anular si no tiene turno, ver detalle con historial y listar los contenedores
propios con aislamiento por naviera (§7.5.2).
"""

from collections.abc import Callable
from datetime import datetime

from web.repositorios.repositorio_manifiestos import (
    ContenedorPropio,
    DetalleManifiesto,
    RepositorioManifiestos,
    ResumenManifiesto,
)
from web.tiempo import marca_utc


class ServicioManifiestos:
    """Operaciones de NAVIERA sobre manifiestos (§14.7)."""

    def __init__(
        self,
        manifiestos: RepositorioManifiestos,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._manifiestos = manifiestos
        self._fabrica_instante = fabrica_instante

    def listar(self, naviera_id: int | None) -> list["ResumenManifiesto"]:
        return self._manifiestos.listar(naviera_id=naviera_id)

    def crear(
        self,
        naviera_id: int,
        contenedor_id: str,
        tipo_op: str,
        peso_declarado_g: int,
        tolerancia_pct: int,
        transportista_id: int,
        observaciones: str,
    ) -> tuple[bool, str | int]:
        return self._manifiestos.crear(
            naviera_id,
            contenedor_id,
            tipo_op,
            peso_declarado_g,
            tolerancia_pct,
            transportista_id,
            observaciones,
            marca_utc(self._fabrica_instante()),
        )

    def anular(self, manifiesto_id: int, naviera_id: int) -> bool:
        return self._manifiestos.anular(manifiesto_id, naviera_id)

    def detalle(
        self, manifiesto_id: int, naviera_id: int | None = None
    ) -> DetalleManifiesto | None:
        """Con ``naviera_id`` solo devuelve el manifiesto si es de esa naviera (§7.4)."""
        return self._manifiestos.detalle_con_historial(manifiesto_id, naviera_id)

    def existe(self, manifiesto_id: int) -> bool:
        return self._manifiestos.buscar_por_id(manifiesto_id) is not None

    def mis_contenedores(self, naviera_id: int) -> list[ContenedorPropio]:
        return self._manifiestos.mis_contenedores(naviera_id)
