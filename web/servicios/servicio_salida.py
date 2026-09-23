"""Verificación de salida y cierre del turno (SPECS §8.6).

Flujo [DEC de valores SAL, documentado en docs/protocolo_serial.md §3.1]:
el primer ``SAL`` con ``resultado=DETECTADO`` identifica al vehículo en el
punto de salida; si coincide con el turno en ``EnSalida`` se envía
``AbrirPuertaSalida``; cuando el controlador confirma el paso con
``resultado=CONFIRMADO`` el turno pasa a ``Cerrado`` (regla §8.2 regla 5).
Un vehículo en salida que no corresponde a ningún turno en ``EnSalida``
genera **AL10** y no se autoriza (§8.6, §13.1).
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.alarma import CodigoAlarma
from web.modelos.turno import EstadoTurno, Turno
from web.repositorios.repositorio_alarmas import RepositorioAlarmas
from web.repositorios.repositorio_citas import RepositorioCitas
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_notificaciones import RepositorioNotificaciones
from web.repositorios.repositorio_turnos import RepositorioTurnos
from web.repositorios.repositorio_vehiculos import RepositorioVehiculos
from web.servicios.puertos import PublicadorLogica
from web.servicios.servicio_turnos import ServicioTurnos
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

TOPICO_SRV_TURNO = "portus/srv/turno"
TIPO_NOTIFICACION_CIERRE = "notificacion.turno_cerrado"

CMD_ABRIR_PUERTA_SALIDA = "AbrirPuertaSalida"
SAL_DETECTADO = "DETECTADO"
SAL_CONFIRMADO = "CONFIRMADO"


class ServicioSalida:
    """Compara SAL con el turno en EnSalida, abre la puerta y cierra el turno (§8.6)."""

    def __init__(
        self,
        vehiculos: RepositorioVehiculos,
        turnos_repo: RepositorioTurnos,
        manifiestos: RepositorioManifiestos,
        citas: RepositorioCitas,
        notificaciones: RepositorioNotificaciones,
        alarmas: RepositorioAlarmas,
        maquina: ServicioTurnos,
        publicador: PublicadorLogica,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._vehiculos = vehiculos
        self._turnos_repo = turnos_repo
        self._manifiestos = manifiestos
        self._citas = citas
        self._notificaciones = notificaciones
        self._alarmas_repo = alarmas
        self._maquina = maquina
        self._publicador = publicador
        self._fabrica_instante = fabrica_instante

    def procesar_salida(
        self, identificador: str, resultado: str, causa: str | None, seq: int | None
    ) -> None:
        """Atiende un SAL: DETECTADO dispara la verificación; CONFIRMADO cierra (§8.6)."""
        if resultado == SAL_DETECTADO:
            self._verificar(identificador, seq)
        elif resultado == SAL_CONFIRMADO:
            self._confirmar(identificador, seq)
        else:
            REGISTRO.warning(
                "SAL con resultado desconocido '%s' para '%s'; se descarta (P-5)",
                resultado,
                identificador,
            )
        _ = causa  # la causa del controlador queda en el registro del evento

    def _verificar(self, identificador: str, seq: int | None) -> None:
        """Compara el vehículo detectado con el turno en EnSalida; AL10 si no coincide."""
        turno = self._turno_en_salida(identificador)
        if turno is None:
            self._alarmar_al10(identificador, "sin turno en EnSalida que coincida")
            return
        self._maquina.registrar_evento(
            turno,
            tipo="salida.verificada",
            descripcion="Vehículo reconocido en la salida: se autoriza abrir la puerta",
            valores={"vehiculo": identificador},
            origen="controlador",
            seq=seq,
        )
        self._publicador.publicar_comando(CMD_ABRIR_PUERTA_SALIDA, {}, "servidor")
        REGISTRO.info("SAL coincide con el turno %d: AbrirPuertaSalida enviado", turno.id)

    def _confirmar(self, identificador: str, seq: int | None) -> None:
        """Salida confirmada: el turno se cierra y la cita queda cumplida (§8.2 regla 5)."""
        turno = self._turno_en_salida(identificador)
        if turno is None:
            self._alarmar_al10(identificador, "confirmación de salida sin turno en EnSalida")
            return
        cerrado = self._maquina.cerrar(turno, origen="controlador", seq=seq)
        self._maquina.registrar_evento(
            cerrado,
            tipo="salida.confirmada",
            descripcion="Salida confirmada por el controlador: operación completada",
            valores={"vehiculo": identificador},
            origen="controlador",
            seq=seq,
        )
        self._notificar_cierre(cerrado)
        REGISTRO.info("Turno %d cerrado: salida confirmada de '%s'", cerrado.id, identificador)

    def autorizar_salida_anulacion(self, turno: Turno) -> None:
        """Anulación: salida autorizada sin completar la operación (§8.2 regla 4, §8.6.3).

        El inventario conserva la posición física real (lo confirman los PAT);
        la notificación 9 sale por el mismo canal que el cierre (§15.3).
        """
        self._publicador.publicar_comando(CMD_ABRIR_PUERTA_SALIDA, {}, "servidor")
        self._maquina.registrar_evento(
            turno,
            tipo="salida.sin_completar",
            descripcion="Turno anulado: salida del vehículo autorizada sin completar",
            valores={"vehiculo_id": turno.vehiculo_id},
            origen="servidor",
        )
        manifiesto = self._manifiestos.buscar_por_id(turno.manifiesto_id)
        transportista_id = (
            manifiesto.transportista_id if manifiesto is not None else turno.vehiculo_id
        )
        payload: dict[str, object] = {
            "turno": turno.id,
            "contenedor": manifiesto.contenedor_id if manifiesto is not None else "",
            "resultado": "anulado",
        }
        self._notificaciones.crear(
            transportista_id, "turno_anulado", payload, marca_utc(self._fabrica_instante())
        )
        self._publicador.publicar(
            TOPICO_SRV_TURNO,
            TIPO_NOTIFICACION_CIERRE,
            {**payload, "transportista": transportista_id},
        )

    def _turno_en_salida(self, identificador: str) -> Turno | None:
        """El turno activo del vehículo, válido solo si está en ``EnSalida`` (§8.6)."""
        vehiculo = self._vehiculos.buscar_por_identificador(identificador)
        if vehiculo is None:
            return None
        turno = self._turnos_repo.activo_de_vehiculo(vehiculo.id)
        if turno is None or turno.estado is not EstadoTurno.EN_SALIDA:
            return None
        return turno

    def _alarmar_al10(self, identificador: str, detalle: str) -> None:
        """AL10: el servidor genera la alarma y no autoriza la salida (§8.6, §13.1)."""
        ts = marca_utc(self._fabrica_instante())
        datos: dict[str, object] = {"vehiculo": identificador, "detalle": detalle}
        self._alarmas_registrar(datos, ts)
        self._publicador.publicar(
            "portus/srv/alarma", "alarma.servidor", {"codigo": CodigoAlarma.AL10.value, **datos}
        )
        REGISTRO.warning(
            "AL10: vehículo incorrecto en la salida ('%s'): %s", identificador, detalle
        )

    def _alarmas_registrar(self, datos: dict[str, object], ts: str) -> None:
        """Persistencia de AL10 en la tabla de alarmas (§13.2)."""
        self._alarmas_repo.registrar(
            CodigoAlarma.AL10.value,
            "MEDIA",
            "servidor",
            "Vehículo incorrecto en la salida",
            datos,
            ts,
        )

    def _notificar_cierre(self, turno: Turno) -> None:
        """Notificación 8 al transportista: operación completada (§8.6, §15.3)."""
        manifiesto = self._manifiestos.buscar_por_id(turno.manifiesto_id)
        transportista_id = (
            manifiesto.transportista_id if manifiesto is not None else turno.vehiculo_id
        )
        payload: dict[str, object] = {
            "turno": turno.id,
            "contenedor": manifiesto.contenedor_id if manifiesto is not None else "",
            "resultado": "completado",
        }
        self._notificaciones.crear(
            transportista_id, "turno_completado", payload, marca_utc(self._fabrica_instante())
        )
        self._publicador.publicar(
            TOPICO_SRV_TURNO,
            TIPO_NOTIFICACION_CIERRE,
            {**payload, "transportista": transportista_id},
        )
