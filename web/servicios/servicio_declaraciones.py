"""AGENTE: declaraciones y seguimiento (SPECS §14.8, §9.1, §9.3, Etapa 7).

Presenta la declaración de mercancías (número único, régimen, descripción ≥ 10,
valor > 0) sobre un manifiesto, solicita el levante (solo si la declaración ya
fue presentada) y adjunta observaciones visibles para la AUTORIDAD.
"""

from collections.abc import Callable
from datetime import datetime

from web.modelos.declaracion import Regimen
from web.repositorios.repositorio_declaraciones import RepositorioDeclaraciones
from web.repositorios.repositorio_levantes import RepositorioLevantes
from web.repositorios.repositorio_manifiestos import ManifiestoVigente, RepositorioManifiestos
from web.tiempo import marca_utc


class ServicioDeclaraciones:
    """Operaciones del AGENTE en la cadena documental (§14.8)."""

    def __init__(
        self,
        declaraciones: RepositorioDeclaraciones,
        manifiestos: RepositorioManifiestos,
        levantes: RepositorioLevantes,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._declaraciones = declaraciones
        self._manifiestos = manifiestos
        self._levantes = levantes
        self._fabrica_instante = fabrica_instante

    def bandeja_sin_levante(self) -> list["ManifiestoVigente"]:
        """Manifiestos de cualquier naviera sin levante para el AGENTE (§14.8)."""
        return self._manifiestos.sin_levante()

    def presentar(
        self,
        agente_id: int,
        manifiesto_id: int,
        numero: str,
        regimen: Regimen,
        descripcion: str,
        valor: int,
    ) -> tuple[bool, str | int]:
        """Presenta la declaración; valida el manifiesto antes de tocar la BD (§9.3).

        Causas: ``MANIFIESTO_INEXISTENTE``, ``MANIFIESTO_NO_DECLARABLE`` (anulado,
        con turno o ya con levante) y ``DECLARACION_EXISTENTE``.
        """
        manifiesto = self._manifiestos.buscar_por_id(manifiesto_id)
        if manifiesto is None:
            return (False, "MANIFIESTO_INEXISTENTE")
        if manifiesto.estado_operativo != "sin_turno" or manifiesto.estado_documental not in (
            "declarado",
            "declaracion_presentada",
        ):
            return (False, "MANIFIESTO_NO_DECLARABLE")
        if self._declaraciones.de_manifiesto(manifiesto_id) is not None:
            return (False, "DECLARACION_EXISTENTE")
        ok, resultado = self._declaraciones.crear(
            manifiesto_id,
            agente_id,
            numero,
            regimen,
            descripcion,
            valor,
            marca_utc(self._fabrica_instante()),
        )
        if ok:
            self._manifiestos.marcar_documental(manifiesto_id, "declaracion_presentada")
        return (ok, resultado)

    def solicitar_levante(self, agente_id: int, manifiesto_id: int) -> tuple[bool, str | int]:
        """Solicita el levante; solo si la declaración ya fue presentada (§9.1)."""
        declaracion = self._declaraciones.de_manifiesto(manifiesto_id)
        if declaracion is None:
            return (False, "SIN_DECLARACION")
        previo = self._levantes.de_manifiesto(manifiesto_id)
        if previo is not None and previo.estado != "sin_solicitud":
            return (False, "LEVANTE_YA_SOLICITADO")
        levante_id = self._levantes.solicitar(
            manifiesto_id, agente_id, marca_utc(self._fabrica_instante())
        )
        self._manifiestos.marcar_documental(manifiesto_id, "levante_solicitado")
        return (True, levante_id)

    def adjuntar_observacion(self, manifiesto_id: int, observacion: str) -> bool:
        return self._manifiestos.adjuntar_observacion(manifiesto_id, observacion)
