"""Parqueo de retención de 3 plazas lógicas (SPECS §10.1, §10.6, §6.3).

Dueño de las plazas: asignación de la libre de menor número (o AL11 si están
las tres ocupadas), ``AgujaParqueo`` cuando el vehículo pasa por el ramal y
``AgujaLiberar`` al resolver. La BD sigue al controlador: con ramal, la plaza
se libera solo con el ACK de ``AgujaLiberar``; si este lo rechaza, el
vehículo sigue ahí y el TERMINAL usa «Liberar parqueo» (§6.3, §23.3).
"""

import logging
import threading

from web.modelos.alarma import CodigoAlarma
from web.modelos.retencion import CausaRetencion, Retencion
from web.modelos.turno import Turno
from web.repositorios.repositorio_plazas import ErrorPlaza, Plaza, RepositorioPlazas
from web.repositorios.repositorio_retenciones import RepositorioRetenciones
from web.servicios.avisos_retencion import AvisosRetencion
from web.servicios.emisor_alarmas import EmisorAlarmas
from web.servicios.puertos import PublicadorLogica

REGISTRO = logging.getLogger(__name__)

CMD_AGUJA_PARQUEO = "AgujaParqueo"
CMD_AGUJA_LIBERAR = "AgujaLiberar"
ESTADO_ACK = "ACK"
USUARIO_SERVIDOR = "servidor"

ESTACIONES_CON_RAMAL = ("garita", "pesaje_entrada")
"""Estaciones desde las que el vehículo retenido entra físicamente al parqueo (§10.1)."""
CAPACIDAD_LIBERACIONES_PENDIENTES = 16


class ErrorPlazaParqueo(Exception):
    """«Liberar parqueo» no aplica: plaza inexistente, libre o con retención abierta (§6.3)."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


class ServicioParqueo:
    """Asigna, envía y libera plazas del ramal siguiendo al controlador."""

    def __init__(
        self,
        plazas: RepositorioPlazas,
        retenciones: RepositorioRetenciones,
        alarmas: EmisorAlarmas,
        avisos: AvisosRetencion,
        publicador: PublicadorLogica,
    ) -> None:
        self._plazas = plazas
        self._retenciones = retenciones
        self._alarmas = alarmas
        self._avisos = avisos
        self._publicador = publicador
        # cmd_id de AgujaLiberar → plaza; lo consume el hilo del cliente MQTT.
        self._liberaciones_pendientes: dict[str, int] = {}
        self._candado = threading.Lock()

    # --------------------------------------------------------------- asignar

    def tomar_plaza(self, turno: Turno, causa: CausaRetencion, instante: str) -> int | None:
        """Plaza del turno si ya la tiene; si no, la libre de menor número o AL11 (§10.1)."""
        propia = self._plazas.de_turno(turno.id)
        if propia is not None:
            return propia.numero
        try:
            return self._plazas.asignar(turno.id, instante)
        except ErrorPlaza:
            self._alarmar_parqueo_lleno(turno, causa, instante)
            return None

    def enviar_al_parqueo(self, plaza: int, turno_id: int, estacion: str) -> None:
        """Publica la ocupación y desvía la aguja si el vehículo pasa por el ramal."""
        self._avisos.plaza(plaza, turno_id)
        if estacion in ESTACIONES_CON_RAMAL:
            self._publicador.publicar_comando(CMD_AGUJA_PARQUEO, {}, USUARIO_SERVIDOR)

    def _alarmar_parqueo_lleno(self, turno: Turno, causa: CausaRetencion, instante: str) -> None:
        datos: dict[str, object] = {"turno": turno.id, "causa": causa.value}
        self._alarmas.emitir(CodigoAlarma.AL11, datos, instante)
        REGISTRO.warning("Sin plaza para el turno %d (%s): AL11", turno.id, causa.value)

    # --------------------------------------------------------------- liberar

    def liberar_por_resolucion(self, retencion: Retencion) -> None:
        """AgujaLiberar si el vehículo fue al ramal; si no, libera la plaza lógica (§10.1.4)."""
        if retencion.plaza is None:
            return
        if retencion.estacion in ESTACIONES_CON_RAMAL:
            self._comandar_liberacion(retencion.plaza, USUARIO_SERVIDOR)
        else:
            self._plazas.liberar(retencion.plaza)
            self._avisos.plaza(retencion.plaza, None)

    def liberar_parqueo(self, numero: int, usuario: str) -> str:
        """«Liberar parqueo» manual: solo plaza ocupada con retención resuelta (§6.3)."""
        plaza = self._plaza(numero)
        if plaza is None:
            raise ErrorPlazaParqueo("PLAZA_INEXISTENTE", f"no existe la plaza {numero}")
        if plaza.turno_id is None:
            raise ErrorPlazaParqueo("PLAZA_LIBRE", f"la plaza {numero} no está ocupada")
        if self._retenciones.abierta_de_turno(plaza.turno_id) is not None:
            raise ErrorPlazaParqueo(
                "RETENCION_ABIERTA",
                f"la retención del turno {plaza.turno_id} (plaza {numero}) no está resuelta",
            )
        return self._comandar_liberacion(numero, usuario)

    def aplicar_respuesta_comando(self, cmd_id: str, estado: str, sintetica: bool) -> None:
        """Libera la plaza cuando el controlador confirma AgujaLiberar (§10.1 paso 4)."""
        with self._candado:
            numero = self._liberaciones_pendientes.get(cmd_id)
            # Un NAK sintético no cierra la espera: el ACK real puede llegar tarde.
            if numero is None or (sintetica and estado != ESTADO_ACK):
                return
            del self._liberaciones_pendientes[cmd_id]
        if estado != ESTADO_ACK:
            REGISTRO.warning(
                "cmd_id=%s: AgujaLiberar rechazado; plaza %d sigue ocupada", cmd_id, numero
            )
            return
        if self._retiene(numero):
            # El turno volvió a retenerse antes del ACK y reusa la plaza (§10.1).
            REGISTRO.info("cmd_id=%s: plaza %d sigue con retención abierta", cmd_id, numero)
            return
        segundos = self._plazas.liberar(numero)
        self._avisos.plaza(numero, None)
        REGISTRO.info(
            "cmd_id=%s: plaza %d liberada (ACK de AgujaLiberar) tras %.0f s",
            cmd_id,
            numero,
            segundos,
        )

    # ---------------------------------------------------------------- lectura

    def estado(self) -> list[dict[str, object]]:
        """Plazas con su turno y si la retención ya se resolvió, para el sinóptico (§14.1)."""
        return [
            {
                "numero": p.numero,
                "turno_id": p.turno_id,
                "ocupada_desde": p.ocupada_desde,
                "retencion_resuelta": p.turno_id is not None
                and self._retenciones.abierta_de_turno(p.turno_id) is None,
            }
            for p in self._plazas.todas()
        ]

    def _plaza(self, numero: int) -> Plaza | None:
        return next((p for p in self._plazas.todas() if p.numero == numero), None)

    def _retiene(self, numero: int) -> bool:
        """True si la plaza está ocupada por un turno con retención abierta."""
        plaza = self._plaza(numero)
        return (
            plaza is not None
            and plaza.turno_id is not None
            and self._retenciones.abierta_de_turno(plaza.turno_id) is not None
        )

    def _comandar_liberacion(self, numero: int, usuario: str) -> str:
        with self._candado:
            cmd_id = self._publicador.publicar_comando(
                CMD_AGUJA_LIBERAR, {"plaza": str(numero)}, usuario
            )
            self._liberaciones_pendientes[cmd_id] = numero
            while len(self._liberaciones_pendientes) > CAPACIDAD_LIBERACIONES_PENDIENTES:
                self._liberaciones_pendientes.pop(next(iter(self._liberaciones_pendientes)))
        return cmd_id
