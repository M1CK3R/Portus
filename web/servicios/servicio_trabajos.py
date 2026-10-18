"""Trabajos de grúa del turno (SPECS §12.5, §12.5.1): plan, JOB y confirmaciones.

El servidor planifica la cola del turno (depósito, retiro con sus remociones),
la envía al controlador como ``JOB`` (§4.4) y la actualiza **solo** con las
confirmaciones físicas ``GRU``/``PAT`` (§8.2 regla 2): un aborto devuelve el
trabajo a la cola sin tocar el inventario (§12.3). Cada ciclo se registra con
su inicio real (envío del JOB) y la distancia derivada en posiciones (A16).
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.ciclo_grua import ResultadoCiclo, distancia_de_ciclo
from web.modelos.patio import CeldaInventario, PoliticaAsignacion
from web.modelos.trabajos import ORIGEN_VEHICULO, EstadoTrabajo, TipoTrabajo, Trabajo
from web.modelos.turno import EstadoTurno, Turno
from web.repositorios.repositorio_inventario import RepositorioInventario
from web.repositorios.repositorio_trabajos import RepositorioTrabajos
from web.repositorios.repositorio_turnos import RepositorioTurnos
from web.repositorios.repositorio_vehiculos import RepositorioVehiculos
from web.servicios.puertos import PublicadorLogica
from web.servicios.servicio_turnos import ServicioTurnos
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

TOPICO_SRV_TURNO = "portus/srv/turno"
TIPO_TURNO_TRABAJO = "turno.trabajo"
TOPICO_SRV_PATIO = "portus/srv/patio"
TIPO_PATIO_ESTADO = "patio.estado"

PASO_FIN = "FIN"
PASO_ABORTO = "ABORTO"
RESULTADO_OK = "OK"


class ServicioTrabajos:
    """Planifica la cola del turno y la avanza con confirmaciones del controlador."""

    def __init__(
        self,
        trabajos: RepositorioTrabajos,
        inventario: RepositorioInventario,
        turnos_repo: RepositorioTurnos,
        vehiculos: RepositorioVehiculos,
        maquina: ServicioTurnos,
        politica: PoliticaAsignacion,
        posiciones: tuple[str, ...],
        publicador: PublicadorLogica,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._trabajos = trabajos
        self._inventario = inventario
        self._turnos_repo = turnos_repo
        self._vehiculos = vehiculos
        self._maquina = maquina
        self._politica = politica
        self._posiciones = posiciones
        self._publicador = publicador
        self._fabrica_instante = fabrica_instante

    # ------------------------------------------------------------- planificar

    def planificar_para_turno(
        self, turno: Turno, contenedor_id: str, creado_en: str
    ) -> list[Trabajo]:
        """Construye el plan del turno según el tipo de operación (§12.5).

        Depósito: un trabajo del vehículo a la posición reservada. Retiro: las
        remociones de los contenedores apilados encima (cada una a una celda
        libre reservada) y al final el retiro del objetivo; el retiro no
        inicia hasta completar las remociones porque la cola es ordenada.
        """
        plan: list[tuple[TipoTrabajo, str, str, str, int]] = []
        if turno.tipo_op == "DEPOSITO":
            if turno.posicion_patio is None or turno.nivel is None:
                mensaje = f"el turno {turno.id} no tiene posición de patio asignada"
                raise ValueError(mensaje)
            plan.append(
                (
                    TipoTrabajo.DEPOSITO,
                    contenedor_id,
                    ORIGEN_VEHICULO,
                    turno.posicion_patio,
                    turno.nivel,
                )
            )
        else:
            objetivo = self._inventario.celda_de_contenedor(contenedor_id)
            if objetivo is None:
                mensaje = f"el contenedor {contenedor_id} no está en el inventario del patio"
                raise ValueError(mensaje)
            for encima, contenedor_encima in self._encima_de(objetivo.posicion, objetivo.nivel):
                destino_pos, destino_nivel = self._asignar_celda_libre()
                self._inventario.reservar(destino_pos)
                plan.append(
                    (
                        TipoTrabajo.REMOCION,
                        contenedor_encima,
                        f"{encima.posicion}/N{encima.nivel}",
                        f"{destino_pos}/N{destino_nivel}",
                        destino_nivel,
                    )
                )
            plan.append(
                (
                    TipoTrabajo.RETIRO,
                    contenedor_id,
                    f"{objetivo.posicion}/N{objetivo.nivel}",
                    ORIGEN_VEHICULO,
                    objetivo.nivel,
                )
            )
        plan_creado = self._trabajos.planificar(turno.id, plan, creado_en)
        self._maquina.registrar_evento(
            turno,
            tipo="trabajo.planificado",
            descripcion=f"Plan de {len(plan_creado)} trabajo(s) de grúa",
            valores={
                "trabajos": [
                    {
                        "id": t.id,
                        "tipo": t.tipo.value,
                        "origen": t.origen,
                        "destino": t.destino,
                        "nivel": t.nivel,
                    }
                    for t in plan_creado
                ]
            },
            origen="servidor",
        )
        return plan_creado

    def _encima_de(self, posicion: str, nivel: int) -> list[tuple[CeldaInventario, str]]:
        """Pares (celda, contenedor) confirmados en la misma posición a un nivel superior."""
        return [
            (celda, str(celda.contenedor_id))
            for celda in self._inventario.celdas()
            if celda.posicion == posicion and celda.nivel > nivel and celda.contenedor_id
        ]

    def _asignar_celda_libre(self) -> tuple[str, int]:
        celdas = tuple(self._inventario.celdas())
        posiciones = tuple(self._inventario.posiciones())
        return self._politica.asignar_posicion("", celdas, posiciones)

    def asignar_celda_para_deposito(self) -> tuple[str, int]:
        """Celda libre según la política activa para reservarla al autorizar (§12.3, §12.4)."""
        return self._asignar_celda_libre()

    # ----------------------------------------------------------- cola y JOB

    def iniciar_siguiente(self, turno: Turno) -> Trabajo | None:
        """Envía el siguiente trabajo pendiente como JOB (§12.5.1, §4.4).

        Mientras haya un trabajo EN_CURSO o el plan esté completo devuelve
        None: el retiro no inicia hasta completar las remociones (§12.5).
        """
        pendientes = [
            t for t in self._trabajos.del_turno(turno.id) if t.estado is EstadoTrabajo.PENDIENTE
        ]
        if not pendientes or self._trabajos.en_curso(turno.id) is not None:
            return None
        siguiente = pendientes[0]
        self._trabajos.marcar_en_curso(siguiente.id, marca_utc(self._fabrica_instante()))
        self._publicador.publicar(
            TOPICO_SRV_TURNO,
            TIPO_TURNO_TRABAJO,
            {
                "trabajo": siguiente.id,
                "turno": turno.id,
                "tipo": siguiente.tipo.value,
                "origen": siguiente.origen,
                "destino": siguiente.destino,
                "nivel": siguiente.nivel,
                "contenedor": siguiente.contenedor_id,
            },
        )
        REGISTRO.info(
            "JOB enviado: trabajo=%d tipo=%s turno=%d contenedor=%s",
            siguiente.id,
            siguiente.tipo.value,
            turno.id,
            siguiente.contenedor_id,
        )
        return siguiente

    def quedan_pendientes(self, turno_id: int) -> bool:
        return self._trabajos.quedan_pendientes(turno_id)

    def cancelar_pendientes(self, turno: Turno) -> list[Trabajo]:
        """Turno anulado: cancela su cola y libera las reservas sin movimiento físico (§12.3).

        Solo se liberan destinos de trabajos que nunca empezaron; el inventario
        confirmado no cambia, así que coincide con la ubicación física real.
        """
        cancelados = self._trabajos.cancelar_pendientes(turno.id)
        liberadas: list[str] = []
        for trabajo in cancelados:
            if trabajo.destino == ORIGEN_VEHICULO:
                continue
            posicion = trabajo.destino.split("/")[0]
            estado = self._inventario.liberar_reserva(posicion)
            if estado is not None:
                liberadas.append(posicion)
                self._publicador.publicar(
                    TOPICO_SRV_PATIO, TIPO_PATIO_ESTADO, {"posicion": posicion, "estado": estado}
                )
        if cancelados:
            self._maquina.registrar_evento(
                turno,
                tipo="trabajo.cancelado",
                descripcion=f"Turno anulado: {len(cancelados)} trabajo(s) de grúa cancelado(s)",
                valores={
                    "trabajos": [t.id for t in cancelados],
                    "reservas_liberadas": liberadas,
                },
                origen="servidor",
            )
            REGISTRO.info(
                "Turno %d anulado: trabajos %s cancelados, reservas liberadas %s",
                turno.id,
                [t.id for t in cancelados],
                liberadas,
            )
        return cancelados

    # --------------------------------------------------- confirmaciones GRU

    def procesar_transferencia(self, evento: str, identificador: str, seq: int | None) -> None:
        """Atiende TRF: la alineación inicia los JOB; el aborto devuelve el trabajo (§12.5)."""
        if evento == "ALINEADO":
            turno = self._turno_de_vehiculo(identificador)
            if turno is None:
                REGISTRO.warning("TRF de '%s' sin turno activo; se descarta (P-5)", identificador)
                return
            if turno.estado is EstadoTurno.EN_RUTA:
                turno = self._maquina.transicionar(
                    turno,
                    EstadoTurno.EN_TRANSFERENCIA,
                    "Vehículo alineado en la zona de transferencia",
                    {},
                    origen="controlador",
                    seq=seq,
                )
            if turno.estado is EstadoTurno.EN_TRANSFERENCIA:
                self.iniciar_siguiente(turno)
            return
        if evento == "ABORTO":
            REGISTRO.info(
                "TRF aborto de '%s': el trabajo en curso volverá a la cola", identificador
            )
            return
        REGISTRO.info("TRF evento=%s de '%s': sin efecto en el plan", evento, identificador)

    def _turno_de_vehiculo(self, identificador: str) -> Turno | None:
        """El turno activo a partir del vehículo que reporta TRF (§8.1)."""
        vehiculo = self._vehiculos.buscar_por_identificador(identificador)
        if vehiculo is None:
            return None
        return self._turnos_repo.activo_de_vehiculo(vehiculo.id)

    def procesar_paso_grua(
        self,
        paso: str,
        resultado: str,
        contenedor: str,
        seq: int | None,
        ts: str,
    ) -> None:
        """Aplica una confirmación GRU del controlador sobre el trabajo en curso.

        ``FIN`` con ``OK`` completa el trabajo (y cuenta la remoción); un
        aborto devuelve el trabajo a la cola y lo reenvía; el inventario no
        cambia aquí sino con PAT (§12.3). El ciclo de grúa se registra en
        ambos casos para métricas y gráfica (§12.6).
        """
        turno, trabajo = self._trabajo_en_curso_por_contenedor(contenedor)
        if trabajo is None or turno is None:
            REGISTRO.warning(
                "GRU sin trabajo en curso para el contenedor '%s'; se descarta", contenedor
            )
            return
        if paso == PASO_FIN and resultado == RESULTADO_OK:
            self._completar(turno, trabajo, seq, ts)
            return
        if paso == PASO_ABORTO:
            self._abortar(turno, trabajo, resultado, seq, ts)
            return
        REGISTRO.info(
            "GRU paso=%s resultado=%s del trabajo %d: sin efecto en el plan",
            paso,
            resultado,
            trabajo.id,
        )

    def _completar(self, turno: Turno, trabajo: Trabajo, seq: int | None, ts: str) -> None:
        self._registrar_ciclo(turno, trabajo, ResultadoCiclo.COMPLETADO, ts)
        self._trabajos.completar(trabajo.id)
        if trabajo.tipo is TipoTrabajo.REMOCION:
            self._inventario.incrementar_remociones(trabajo.contenedor_id)
        self._maquina.registrar_evento(
            turno,
            tipo="trabajo.completado",
            descripcion=f"Trabajo {trabajo.tipo.value} confirmado por el controlador",
            valores={"trabajo": trabajo.id, "contenedor": trabajo.contenedor_id},
            origen="controlador",
            seq=seq,
        )
        if self._trabajos.quedan_pendientes(turno.id):
            self.iniciar_siguiente(turno)
            return
        # Plan completo: el vehículo sigue a la plataforma de pesaje de salida.
        if turno.estado is EstadoTurno.EN_TRANSFERENCIA:
            self._maquina.transicionar(
                turno,
                EstadoTurno.EN_PESAJE_SALIDA,
                "Trabajos de grúa completados: el vehículo continúa a pesaje de salida",
                {"trabajo": trabajo.id},
                origen="servidor",
                seq=seq,
            )

    def _abortar(
        self,
        turno: Turno,
        trabajo: Trabajo,
        resultado: str,
        seq: int | None,
        ts: str,
    ) -> None:
        self._registrar_ciclo(turno, trabajo, ResultadoCiclo.ABORTADO, ts)
        self._trabajos.abortar(trabajo.id)
        self._maquina.registrar_evento(
            turno,
            tipo="trabajo.abortado",
            descripcion="Trabajo abortado por el controlador; vuelve a la cola",
            valores={"trabajo": trabajo.id, "resultado": resultado},
            origen="controlador",
            seq=seq,
        )
        actualizado = self._turnos_repo.buscar_por_id(turno.id)
        if actualizado is not None:
            self.iniciar_siguiente(actualizado)

    def _registrar_ciclo(
        self,
        turno: Turno,
        trabajo: Trabajo,
        resultado: ResultadoCiclo,
        ts_fin: str,
    ) -> None:
        """Persiste el ciclo con su inicio real y la distancia en posiciones (§12.6, A16).

        Se registra antes de cambiar el estado del trabajo para que la
        posición de partida sea la del ciclo anterior.
        """
        distancia = distancia_de_ciclo(
            self._trabajos.ultimo_extremo_de_grua(),
            trabajo.origen,
            trabajo.destino,
            resultado,
            self._posiciones,
        )
        self._trabajos.registrar_ciclo(
            turno_id=turno.id,
            trabajo_id=trabajo.id,
            tipo=trabajo.tipo,
            ts_inicio=self._trabajos.inicio_de(trabajo.id) or trabajo.creado_en or ts_fin,
            ts_fin=ts_fin,
            distancia_traslacion=distancia,
            resultado=resultado,
            creado_en=ts_fin,
        )

    def _trabajo_en_curso_por_contenedor(
        self, contenedor: str
    ) -> tuple[Turno | None, Trabajo | None]:
        """El trabajo EN_CURSO de ese contenedor y su turno (los GRU no traen vehículo)."""
        trabajo = self._trabajos.en_curso_de_contenedor(contenedor)
        if trabajo is None:
            return (None, None)
        return (self._turnos_repo.buscar_por_id(trabajo.turno_id), trabajo)
