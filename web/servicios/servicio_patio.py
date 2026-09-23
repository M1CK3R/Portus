"""Patio: aplica las confirmaciones físicas PAT al inventario (SPECS §12.3).

Regla §8.2 regla 2: el inventario solo cambia cuando el controlador confirma
físicamente el movimiento. Un ``PAT`` (``portus/evt/patio``) es la única
fuente de verdad de la ubicación de un contenedor; el comando nunca la
modifica por adelantado. La pestaña Patio (§12.2) y el sinóptico (§14.1) leen
aquí el estado de posiciones e inventario, y el TERMINAL bloquea/libera
posiciones desde aquí (§6.3: PosicionBloquear / PosicionLiberar).
"""

import logging

from web.modelos.patio import CeldaInventario, EstadoDePosicion
from web.repositorios.repositorio_inventario import FilaInventario, RepositorioInventario
from web.servicios.puertos import PublicadorLogica

REGISTRO = logging.getLogger(__name__)

ESTADO_PAT_OCUPADA = "OCUPADA"
ESTADO_PAT_LIBRE = "LIBRE"

TOPICO_SRV_TURNO = "portus/srv/turno"
TIPO_PATIO_ACTUALIZADO = "patio.actualizado"
TOPICO_SRV_PATIO = "portus/srv/patio"
TIPO_PATIO_ESTADO = "patio.estado"


class ServicioPatio:
    """Materializa PAT en el inventario y refleja el patio en el tablero."""

    def __init__(self, inventario: RepositorioInventario, publicador: PublicadorLogica) -> None:
        self._inventario = inventario
        self._publicador = publicador

    def procesar_cambio_posicion(
        self, posicion: str, nivel: int, contenedor: str, estado: str, ts: str
    ) -> None:
        """Aplica un PAT confirmado: ocupación o liberación de una celda (§12.3)."""
        if estado == ESTADO_PAT_OCUPADA:
            self._inventario.confirmar_ocupacion(contenedor, posicion, nivel, ts)
            descripcion = f"{contenedor} en {posicion}/N{nivel} (confirmado)"
        elif estado == ESTADO_PAT_LIBRE:
            self._inventario.confirmar_retiro(contenedor, posicion, nivel)
            descripcion = f"{posicion}/N{nivel} liberada (confirmado)"
        else:
            # P-5: un estado de posición desconocido no detiene al consumidor.
            REGISTRO.warning(
                "PAT con estado desconocido '%s' en %s/N%d (%s); se descarta",
                estado,
                posicion,
                nivel,
                contenedor,
            )
            return
        self._publicador.publicar(
            TOPICO_SRV_TURNO,
            TIPO_PATIO_ACTUALIZADO,
            {
                "posicion": posicion,
                "nivel": nivel,
                "contenedor": contenedor,
                "estado": estado,
                "ts": ts,
            },
        )
        REGISTRO.info("Inventario actualizado por PAT: %s", descripcion)

    # ----------------------------------------------------- pestaña Patio §12.2

    def posiciones(self) -> list[EstadoDePosicion]:
        """Posiciones del patio con su estado base (§12.1, §14.4)."""
        return self._inventario.posiciones()

    def celdas(self) -> list[CeldaInventario]:
        """Celdas (posición, nivel) con su contenedor (§12.2, §14.1 sinóptico)."""
        return self._inventario.celdas()

    def inventario_completo(self) -> list[FilaInventario]:
        """Inventario por contenedor con los 8 campos (§12.2)."""
        return self._inventario.inventario_completo()

    def bloquear_posicion(self, posicion_id: str) -> bool:
        """Bloquea una posición libre (§6.3 PosicionBloquear, §12.2)."""
        ok = self._inventario.bloquear(posicion_id)
        if ok:
            self._publicar_estado(posicion_id, "bloqueada")
        return ok

    def liberar_posicion(self, posicion_id: str) -> bool:
        """Libera el bloqueo de una posición (§6.3 PosicionLiberar, §12.2)."""
        ok = self._inventario.desbloquear(posicion_id)
        if ok:
            self._publicar_estado(posicion_id, "libre")
        return ok

    def _publicar_estado(self, posicion_id: str, estado: str) -> None:
        """Publica el cambio de estado de una posición para el sinóptico (§14.1)."""
        self._publicador.publicar(
            TOPICO_SRV_PATIO,
            TIPO_PATIO_ESTADO,
            {"posicion": posicion_id, "estado": estado},
        )
