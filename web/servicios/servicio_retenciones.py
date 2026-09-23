"""Retenciones y parqueo (SPECS §10): retener, asignar plaza y resolver.

Reglas aplicadas aquí: plaza libre de menor número con transacción (§10.1,
§10.6), ``AgujaParqueo`` al retener y ``AgujaLiberar`` al resolver (solo
cuando el vehículo está antes de la aguja; una retención tardía mantiene el
vehículo en su punto con plaza lógica, A3 [DEC]), resoluciones con rol
facultado (§10.2), Corregir solo TERMINAL en RT01/RT02 (A12), Rechazar exige
motivo y autoriza la salida (§10.3), y toda resolución notifica (§10.7).
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.alarma import CodigoAlarma
from web.modelos.retencion import (
    CausaRetencion,
    ResolucionRetencion,
    Retencion,
    puede_resolver,
)
from web.modelos.turno import EstadoTurno, Turno
from web.modelos.usuario import Usuario
from web.repositorios.repositorio_alarmas import RepositorioAlarmas
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_notificaciones import RepositorioNotificaciones
from web.repositorios.repositorio_plazas import ErrorPlaza, RepositorioPlazas
from web.repositorios.repositorio_retenciones import RepositorioRetenciones
from web.repositorios.repositorio_turnos import RepositorioTurnos
from web.repositorios.repositorio_vehiculos import RepositorioVehiculos
from web.servicios.puertos import PublicadorLogica
from web.servicios.servicio_turnos import ServicioTurnos
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

TOPICO_SRV_RETENCION = "portus/srv/retencion"
TIPO_RETENCION_ABIERTA = "retencion.abierta"
TIPO_RETENCION_RESUELTA = "retencion.resuelta"

CMD_AGUJA_PARQUEO = "AgujaParqueo"
CMD_AGUJA_LIBERAR = "AgujaLiberar"
CMD_ABRIR_PUERTA_SALIDA = "AbrirPuertaSalida"

ESTADOS_PRE_AGUJA = (EstadoTurno.EN_GARITA, EstadoTurno.EN_PESAJE_ENTRADA)
"""Estados desde los que el vehículo puede llegar físicamente al ramal (A3 [DEC])."""


class ErrorRetencion(Exception):
    """Base de los rechazos de la bandeja de retenciones (§10.3)."""


class ErrorRetencionResuelta(ErrorRetencion):
    """Una retención resuelta no puede volver a resolverse (§10.3, §17.3)."""


class ErrorPermisoResolucion(ErrorRetencion):
    """El rol no está facultado para esa causa y resolución (§10.2, §7.5.3)."""


class ErrorMotivoRequerido(ErrorRetencion):
    """Rechazar exige motivo (§10.3)."""


class ErrorRetencionInexistente(ErrorRetencion):
    """No existe la retención indicada (§18: 404)."""


class ServicioRetenciones:
    """Ciclo de vida completo de una retención sobre el parqueo de 3 plazas."""

    def __init__(
        self,
        retenciones: RepositorioRetenciones,
        plazas: RepositorioPlazas,
        vehiculos: RepositorioVehiculos,
        manifiestos: RepositorioManifiestos,
        turnos_repo: RepositorioTurnos,
        alarmas: RepositorioAlarmas,
        notificaciones: RepositorioNotificaciones,
        maquina: ServicioTurnos,
        publicador: PublicadorLogica,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._retenciones = retenciones
        self._plazas = plazas
        self._vehiculos = vehiculos
        self._manifiestos = manifiestos
        self._turnos_repo = turnos_repo
        self._alarmas = alarmas
        self._notificaciones = notificaciones
        self._maquina = maquina
        self._publicador = publicador
        self._fabrica_instante = fabrica_instante

    # --------------------------------------------------------------- retener

    def retener(
        self,
        turno: Turno,
        causa: CausaRetencion,
        estacion: str,
        peso_declarado_g: int | None = None,
        peso_medido_g: int | None = None,
        observacion: str | None = None,
    ) -> Retencion:
        """Abre la retención, toma plaza, mueve el turno a ``Retenido`` y notifica (§10.5).

        Sin plaza libre la retención igual nace (una tardía no puede devolver
        al vehículo al ramal, A3 [DEC]) y genera AL11 (§10.1 paso 6); el
        ``AgujaParqueo`` solo sale si el vehículo está antes de la aguja.
        """
        instante = marca_utc(self._fabrica_instante())
        plaza: int | None = None
        try:
            plaza = self._plazas.asignar(turno.id, instante)
        except ErrorPlaza:
            self._alarmas.registrar(
                CodigoAlarma.AL11.value,
                "MEDIA",
                "servidor",
                "Parqueo de retención lleno",
                {"turno": turno.id, "causa": causa.value},
                instante,
            )
            self._publicador.publicar(
                "portus/srv/alarma",
                "alarma.servidor",
                {"codigo": CodigoAlarma.AL11.value, "turno": turno.id, "causa": causa.value},
            )
            REGISTRO.warning("Sin plaza para el turno %d (%s): AL11", turno.id, causa.value)
        retencion_id = self._retenciones.crear(
            turno.id, causa, estacion, plaza, peso_declarado_g, peso_medido_g, instante
        )
        retenida = self._retenciones.buscar_por_id(retencion_id)
        if retenida is None:
            mensaje = f"la retención {retencion_id} no se encontró tras crearla"
            raise RuntimeError(mensaje)
        self._maquina.transicionar(
            turno,
            EstadoTurno.RETENIDO,
            f"Retención {causa.value} en {estacion}",
            {"retencion": retencion_id, "causa": causa.value, "plaza": plaza},
            origen="servidor",
        )
        if plaza is not None and turno.estado in ESTADOS_PRE_AGUJA:
            self._publicador.publicar_comando(CMD_AGUJA_PARQUEO, {}, "servidor")
        self._notificar_retencion(retenida)
        self._publicador.publicar(
            TOPICO_SRV_RETENCION, TIPO_RETENCION_ABIERTA, _datos_retencion(retenida)
        )
        return retenida

    # -------------------------------------------------------------- resolver

    def resolver(
        self,
        retencion_id: int,
        resolucion: ResolucionRetencion,
        usuario: Usuario,
        motivo: str | None = None,
        observacion: str | None = None,
    ) -> Retencion:
        """Aplica Aclarar, Corregir o Rechazar con sus reglas exactas (§10.3)."""
        retencion = self._retenciones.buscar_por_id(retencion_id)
        if retencion is None:
            raise ErrorRetencionInexistente(f"la retención {retencion_id} no existe")
        if retencion.estado != "abierta":
            raise ErrorRetencionResuelta(f"la retención {retencion_id} ya está resuelta")
        if not puede_resolver(usuario.rol, retencion.causa, resolucion):
            raise ErrorPermisoResolucion(
                f"el rol {usuario.rol.value} no puede aplicar "
                f"{resolucion.value} a {retencion.causa.value}"
            )
        if resolucion is ResolucionRetencion.RECHAZAR and not (motivo and motivo.strip()):
            raise ErrorMotivoRequerido("Rechazar exige un motivo (§10.3)")

        instante = marca_utc(self._fabrica_instante())
        turno = self._turno_de_retencion(retencion)
        if not self._retenciones.resolver(
            retencion_id, resolucion.value, motivo, observacion, usuario.id, instante
        ):
            raise ErrorRetencionResuelta(f"la retención {retencion_id} ya está resuelta")
        self._liberar_y_comandar(retencion)

        if resolucion is ResolucionRetencion.CORREGIR and turno is not None:
            self._corregir_peso(retencion, turno, usuario, instante)
        if resolucion is ResolucionRetencion.RECHAZAR:
            self._rechazar(turno, motivo or "", retencion.id, usuario)
        elif turno is not None and turno.estado is EstadoTurno.RETENIDO:
            regreso = self._maquina.estado_para_regreso(turno)
            self._maquina.transicionar(
                turno,
                regreso,
                f"Retención {retencion.causa.value} resuelta con {resolucion.value}",
                {"retencion": retencion.id, "resolucion": resolucion.value},
                origen="servidor",
            )
        resuelta = self._retenciones.buscar_por_id(retencion_id)
        if resuelta is None:
            mensaje = f"la retención {retencion_id} desapareció al resolverla"
            raise RuntimeError(mensaje)
        self._notificar_resolucion(resuelta)
        self._publicador.publicar(
            TOPICO_SRV_RETENCION, TIPO_RETENCION_RESUELTA, _datos_retencion(resuelta)
        )
        REGISTRO.info(
            "Retención %d resuelta con %s por %s", retencion_id, resolucion.value, usuario.username
        )
        return resuelta

    def _liberar_y_comandar(self, retencion: Retencion) -> None:
        """Libera la plaza y envía AgujaLiberar cuando el vehículo fue al ramal (§10.1 paso 4)."""
        if retencion.plaza is not None:
            self._plazas.liberar(retencion.plaza)
        if retencion.estacion in ("garita", "pesaje_entrada"):
            self._publicador.publicar_comando(CMD_AGUJA_LIBERAR, {}, "servidor")

    def _corregir_peso(
        self, retencion: Retencion, turno: Turno, usuario: Usuario, instante: str
    ) -> None:
        """Corregir: el peso declarado pasa a ser el medido, con historial (§10.3, A12)."""
        if retencion.peso_medido_g is None or retencion.peso_declarado_g is None:
            mensaje = f"la retención {retencion.id} no tiene evidencia de peso para Corregir"
            raise ValueError(mensaje)
        self._manifiestos.corregir_peso(
            turno.manifiesto_id,
            retencion.peso_medido_g,
            retencion.peso_declarado_g,
            retencion.id,
            usuario.id,
            instante,
        )

    def _rechazar(
        self, turno: Turno | None, motivo: str, retencion_id: int, usuario: Usuario
    ) -> None:
        """Rechazar: turno Anulado y salida autorizada sin completar (§10.3, §8.6.3)."""
        if turno is None:
            return
        self._maquina.anular(turno, f"Retención {retencion_id} rechazada: {motivo}", "servidor")
        self._publicador.publicar_comando(CMD_ABRIR_PUERTA_SALIDA, {}, "servidor")
        self._notificar_desenlace(
            turno,
            "turno_anulado",
            {
                "contenedor": self._contenedor_del_turno(turno),
                "motivo": motivo,
            },
        )

    def _turno_de_retencion(self, retencion: Retencion) -> Turno | None:
        return self._turnos_repo.buscar_por_id(retencion.turno_id)

    def _contenedor_del_turno(self, turno: Turno) -> str:
        manifiesto = self._manifiestos.buscar_por_id(turno.manifiesto_id)
        return manifiesto.contenedor_id if manifiesto is not None else ""

    def _vehiculo_del_turno(self, turno: Turno) -> str:
        vehiculo = self._vehiculos.buscar_por_id(turno.vehiculo_id)
        return vehiculo.identificador if vehiculo is not None else ""

    # --------------------------------------------------------- notificaciones

    def _notificar_retencion(self, retencion: Retencion) -> None:
        """Notificación «vehículo retenido» con evidencia de peso si aplica (§10.7)."""
        turno = self._turno_de_retencion(retencion)
        if turno is None:
            return
        payload: dict[str, object] = {
            "vehiculo": self._vehiculo_del_turno(turno),
            "contenedor": self._contenedor_del_turno(turno),
            "causa": retencion.causa.value,
        }
        if retencion.causa.value in ("RT01", "RT02"):
            payload["peso_declarado_g"] = retencion.peso_declarado_g
            payload["peso_medido_g"] = retencion.peso_medido_g
        self._notificar_desenlace(turno, "vehiculo_retenido", payload)

    def _notificar_resolucion(self, retencion: Retencion) -> None:
        """Notificación «retención resuelta» (§10.7): tipo y detalle por resolución."""
        turno = self._turno_de_retencion(retencion)
        if turno is None or retencion.resolucion is None:
            return
        payload: dict[str, object] = {
            "vehiculo": self._vehiculo_del_turno(turno),
            "contenedor": self._contenedor_del_turno(turno),
            "resolucion": retencion.resolucion,
        }
        if retencion.resolucion == "CORREGIR":
            payload["nuevo_peso_declarado_g"] = retencion.peso_medido_g
        if retencion.resolucion == "RECHAZAR":
            payload["motivo"] = retencion.motivo
        self._notificar_desenlace(turno, "retencion_resuelta", payload)

    def _notificar_desenlace(self, turno: Turno, tipo: str, payload: dict[str, object]) -> None:
        manifiesto = self._manifiestos.buscar_por_id(turno.manifiesto_id)
        transportista_id = (
            manifiesto.transportista_id if manifiesto is not None else turno.vehiculo_id
        )
        self._notificaciones.crear(
            transportista_id, tipo, payload, marca_utc(self._fabrica_instante())
        )
        self._publicador.publicar(
            TOPICO_SRV_RETENCION if tipo != "turno_anulado" else "portus/srv/turno",
            f"notificacion.{tipo}",
            {**payload, "transportista": transportista_id},
        )


def _datos_retencion(retencion: Retencion) -> dict[str, object]:
    return {
        "retencion": retencion.id,
        "turno": retencion.turno_id,
        "causa": retencion.causa.value,
        "estacion": retencion.estacion,
        "plaza": retencion.plaza,
        "estado": retencion.estado,
        "peso_declarado_g": retencion.peso_declarado_g,
        "peso_medido_g": retencion.peso_medido_g,
        "resolucion": retencion.resolucion,
        "motivo": retencion.motivo,
    }
