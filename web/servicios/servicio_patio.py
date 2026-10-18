"""Patio: aplica las confirmaciones físicas PAT al inventario (SPECS §12.3).

Regla §8.2 regla 2: el inventario solo cambia cuando el controlador confirma
físicamente el movimiento. Un ``PAT`` (``portus/evt/patio``) es la única
fuente de verdad de la ubicación de un contenedor; el comando nunca la
modifica por adelantado. La pestaña Patio (§12.2) y el sinóptico (§14.1) leen
aquí el estado de posiciones e inventario, y el TERMINAL bloquea/libera
posiciones desde aquí (§6.3: PosicionBloquear / PosicionLiberar).
"""

import logging
import threading

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

COMANDO_POSICION_BLOQUEAR = "PosicionBloquear"
COMANDO_POSICION_LIBERAR = "PosicionLiberar"
ESTADO_POSICION_LIBRE = "libre"
ESTADO_POSICION_BLOQUEADA = "bloqueada"
ESTADO_ACK = "ACK"
CAPACIDAD_PENDIENTES = 64


class ErrorPosicion(Exception):
    """La posición no existe o no está en el estado que el comando exige (§6.3)."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


class ServicioPatio:
    """Materializa PAT en el inventario y refleja el patio en el tablero."""

    def __init__(self, inventario: RepositorioInventario, publicador: PublicadorLogica) -> None:
        self._inventario = inventario
        self._publicador = publicador
        # cmd_id → (comando, posición) a la espera del RSP del controlador.
        self._pendientes: dict[str, tuple[str, str]] = {}
        # Lo escriben los hilos HTTP y lo consume el hilo del cliente MQTT.
        self._candado_pendientes = threading.Lock()

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

    def solicitar_bloqueo(self, posicion_id: str, usuario: str) -> str:
        """Envía PosicionBloquear al controlador y devuelve el ``cmd_id`` (§6.1, §6.3).

        El bloqueo se aplica en la BD solo al llegar el ACK: el controlador
        es quien lo rechaza si la posición está en un trabajo (POS_EN_TRABAJO).
        Lanza :class:`ErrorPosicion` si la posición no existe o no está libre.
        """
        self._exigir_estado(posicion_id, ESTADO_POSICION_LIBRE)
        return self._emitir(COMANDO_POSICION_BLOQUEAR, posicion_id, usuario)

    def solicitar_liberacion(self, posicion_id: str, usuario: str) -> str:
        """Envía PosicionLiberar (solo si está bloqueada) y devuelve el ``cmd_id`` (§6.3)."""
        self._exigir_estado(posicion_id, ESTADO_POSICION_BLOQUEADA)
        return self._emitir(COMANDO_POSICION_LIBERAR, posicion_id, usuario)

    def aplicar_respuesta_comando(self, cmd_id: str, estado: str, sintetica: bool) -> None:
        """Aplica en la BD el bloqueo/liberación que el controlador aceptó (§6.2).

        Un NAK sintético (SIN_RESPUESTA) no descarta la espera: si el ACK real
        llega tarde, el controlador sí ejecutó el comando y la BD debe seguirlo.
        """
        with self._candado_pendientes:
            pendiente = self._pendientes.get(cmd_id)
            if pendiente is None or (sintetica and estado != ESTADO_ACK):
                return
            del self._pendientes[cmd_id]
        nombre, posicion_id = pendiente
        if estado != ESTADO_ACK:
            REGISTRO.info("cmd_id=%s: %s de %s rechazado", cmd_id, nombre, posicion_id)
            return
        if nombre == COMANDO_POSICION_BLOQUEAR:
            aplicado, estado_nuevo = self._inventario.bloquear(posicion_id), "bloqueada"
        else:
            aplicado, estado_nuevo = self._inventario.desbloquear(posicion_id), "libre"
        if not aplicado:
            REGISTRO.warning(
                "cmd_id=%s: ACK de %s pero %s cambió de estado antes de aplicarlo",
                cmd_id,
                nombre,
                posicion_id,
            )
            return
        self._publicar_estado(posicion_id, estado_nuevo)
        REGISTRO.info("cmd_id=%s: %s quedó %s (ACK)", cmd_id, posicion_id, estado_nuevo)

    def _exigir_estado(self, posicion_id: str, esperado: str) -> None:
        actual = next((p.estado for p in self.posiciones() if p.id == posicion_id), None)
        if actual is None:
            raise ErrorPosicion("POSICION_INEXISTENTE", f"no existe la posición {posicion_id}")
        if actual != esperado:
            raise ErrorPosicion(
                "POSICION_NO_" + esperado.upper(),
                f"la posición {posicion_id} está {actual} (se esperaba {esperado})",
            )

    def _emitir(self, nombre: str, posicion_id: str, usuario: str) -> str:
        # Se registra antes de publicar: el RSP podría llegar antes del return.
        with self._candado_pendientes:
            cmd_id = self._publicador.publicar_comando(nombre, {"pos": posicion_id}, usuario)
            self._pendientes[cmd_id] = (nombre, posicion_id)
            # Las respuestas que nunca llegan no deben crecer el mapa sin límite.
            while len(self._pendientes) > CAPACIDAD_PENDIENTES:
                self._pendientes.pop(next(iter(self._pendientes)))
        return cmd_id

    def _publicar_estado(self, posicion_id: str, estado: str) -> None:
        """Publica el cambio de estado de una posición para el sinóptico (§14.1)."""
        self._publicador.publicar(
            TOPICO_SRV_PATIO,
            TIPO_PATIO_ESTADO,
            {"posicion": posicion_id, "estado": estado},
        )
