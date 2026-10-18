"""Máquina de estados del turno en el servidor (SPECS §8, CODESTYLE A-2).

Dueño de las transiciones exactas de §8.1: valida la tabla, persiste el
cambio, escribe la línea de tiempo (§14.2) y publica en ``portus/srv/turno``
para el tablero (§5.3). Los servicios de garita, pesaje, retención y salida
le delegan cada movimiento del turno.
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.turno import (
    ESTADOS_FINALES,
    EstadoTurno,
    Turno,
    estado_de_regreso,
    transicion_valida,
)
from web.repositorios.repositorio_ciclo_cita import RepositorioCicloCita
from web.repositorios.repositorio_citas import RepositorioCitas
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_turnos import RepositorioTurnos
from web.servicios.puertos import PublicadorLogica
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

TOPICO_SRV_TURNO = "portus/srv/turno"
TIPO_TURNO_CAMBIO = "turno.cambio"


class ErrorTransicion(Exception):
    """Transición no permitida por la tabla §8.1 (CODESTYLE D-5)."""


class ServicioTurnos:
    """Aplica §8.1 en el servidor: ninguna transición fuera de la tabla pasa."""

    def __init__(
        self,
        turnos: RepositorioTurnos,
        manifiestos: RepositorioManifiestos,
        citas: RepositorioCitas,
        ciclo_citas: RepositorioCicloCita,
        publicador: PublicadorLogica,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._turnos = turnos
        self._manifiestos = manifiestos
        self._citas = citas
        self._ciclo_citas = ciclo_citas
        self._publicador = publicador
        self._fabrica_instante = fabrica_instante

    def crear_en_garita(
        self,
        vehiculo_id: int,
        manifiesto_id: int,
        cita_id: int | None,
        tipo_op: str,
        canal: str,
        dentro_de_ventana: bool,
        creado_en: str,
        seq: int | None = None,
    ) -> Turno:
        """Crea el turno en ``EnGarita`` al autorizar el ingreso (§8.2 regla 1, A1)."""
        turno_id = self._turnos.crear(
            vehiculo_id, manifiesto_id, cita_id, tipo_op, canal, dentro_de_ventana, creado_en
        )
        turno = self._turnos.buscar_por_id(turno_id)
        if turno is None:  # defensa: el INSERT acaba de correr
            mensaje = f"el turno {turno_id} no se encontró justo después de crearlo"
            raise RuntimeError(mensaje)
        self.registrar_evento(
            turno,
            tipo="turno.creado",
            descripcion="Turno creado al autorizar el ingreso en garita",
            valores={"tipo_op": tipo_op, "canal": canal},
            origen="servidor",
            seq=seq,
        )
        self._manifiestos.marcar_operativo(manifiesto_id, "en_curso")
        self._publicar_cambio(turno)  # estado inicial visible en el tablero (§5.3)
        return turno

    def transicionar(
        self,
        turno: Turno,
        nuevo: EstadoTurno,
        descripcion: str,
        valores: dict[str, object],
        origen: str,
        seq: int | None = None,
    ) -> Turno:
        """Valida y aplica una transición de §8.1; publica el cambio (§5.3).

        Al retener guarda el estado previo (A2); en las demás transiciones el
        campo queda limpio para que el mapa de regreso siempre lea el previo
        de la retención vigente.
        """
        if not transicion_valida(turno.estado, nuevo):
            mensaje = f"transición no permitida por §8.1: {turno.estado.value} → {nuevo.value}"
            raise ErrorTransicion(mensaje)
        previo = turno.estado.value if nuevo is EstadoTurno.RETENIDO else None
        self._turnos.actualizar_estado(turno.id, nuevo, previo)
        actualizado = self._turnos.buscar_por_id(turno.id)
        if actualizado is None:
            mensaje = f"el turno {turno.id} desapareció al actualizar su estado"
            raise RuntimeError(mensaje)
        self.registrar_evento(
            actualizado,
            tipo="turno.transicion",
            descripcion=descripcion,
            valores={**valores, "desde": turno.estado.value, "hacia": nuevo.value},
            origen=origen,
            seq=seq,
        )
        self._publicar_cambio(actualizado)
        REGISTRO.info("Turno %d: %s → %s", turno.id, turno.estado.value, nuevo.value)
        return actualizado

    def estado_para_regreso(self, turno: Turno) -> EstadoTurno:
        """Estado de regreso tras Aclarar/Corregir según el mapa A2 (§8.5)."""
        if turno.estado_previo_retencion is None:
            mensaje = f"el turno {turno.id} no guarda estado previo de retención"
            raise ValueError(mensaje)
        return estado_de_regreso(turno.estado_previo_retencion)

    def cerrar(self, turno: Turno, origen: str, seq: int | None = None) -> Turno:
        """Cierra el turno y sincroniza cita y manifiesto (§8.6, §11.2, §8.3)."""
        cerrado = self.transicionar(
            turno,
            EstadoTurno.CERRADO,
            "Salida confirmada por el controlador: turno cerrado",
            {},
            origen,
            seq,
        )
        self._turnos.actualizar_datos(
            cerrado.id, {"cerrado_en": marca_utc(self._fabrica_instante())}
        )
        if cerrado.cita_id is not None:
            self._citas.marcar_cumplida(cerrado.cita_id)
        self._manifiestos.marcar_operativo(cerrado.manifiesto_id, "completado")
        return self._turnos.buscar_por_id(cerrado.id) or cerrado

    def anular(self, turno: Turno, motivo: str, origen: str, seq: int | None = None) -> Turno:
        """Anula el turno con su motivo; manifiesto y cita reflejan el desenlace (§8.3, A11)."""
        anulado = self.transicionar(
            turno, EstadoTurno.ANULADO, f"Turno anulado: {motivo}", {}, origen, seq
        )
        self._turnos.actualizar_datos(anulado.id, {"motivo_anulacion": motivo})
        self._manifiestos.marcar_operativo(anulado.manifiesto_id, "anulado")
        if anulado.cita_id is not None:
            self._ciclo_citas.cancelar_por_anulacion(anulado.cita_id)
        return self._turnos.buscar_por_id(anulado.id) or anulado

    def registrar_evento(
        self,
        turno: Turno,
        tipo: str,
        descripcion: str,
        valores: dict[str, object],
        origen: str,
        seq: int | None = None,
    ) -> None:
        """Añade una entrada a la línea de tiempo (§14.2)."""
        self._turnos.registrar_evento(
            turno.id, marca_utc(self._fabrica_instante()), origen, tipo, descripcion, valores, seq
        )

    def esta_final(self, turno: Turno) -> bool:
        return turno.estado in ESTADOS_FINALES

    def buscar_turno(self, turno_id: int) -> Turno | None:
        """Lectura pública del turno para los demás servicios (evita atributos privados)."""
        return self._turnos.buscar_por_id(turno_id)

    def actualizar_posicion(self, turno_id: int, posicion: str, nivel: int) -> None:
        """Fija la posición de patio y nivel asignados al turno (§12.3)."""
        self._turnos.actualizar_datos(turno_id, {"posicion_patio": posicion, "nivel": nivel})

    def _publicar_cambio(self, turno: Turno) -> None:
        self._publicador.publicar(
            TOPICO_SRV_TURNO,
            TIPO_TURNO_CAMBIO,
            {
                "turno": turno.id,
                "estado": turno.estado.value,
                "estado_previo_retencion": turno.estado_previo_retencion,
                "posicion_patio": turno.posicion_patio,
                "nivel": turno.nivel,
                "vehiculo_id": turno.vehiculo_id,
                "manifiesto_id": turno.manifiesto_id,
                "tipo_op": turno.tipo_op,
            },
        )
