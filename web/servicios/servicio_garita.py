"""Validación de ingreso en garita (SPECS §9.4) y autorización AUT (§4.4).

Orden exacto de la cadena: vehículo registrado → manifiesto vigente →
levante otorgado (no retenido) → cita vigente → riesgo de retención (canal
rojo o fuera de ventana) con plaza disponible. Un rechazo no crea turno pero
queda registrado con su causa (§8.2 regla 1); la autorización crea el turno
en ``EnGarita`` (A1), reserva la posición (depósito), planifica los trabajos
de grúa y — si hay riesgo con plaza disponible — retiene al ingresar (RT04,
§9.4). Fuera de ventana con plaza NO es rechazo (RT04); canal rojo entra y se
retiene tras el pesaje de entrada (RT03, §9.2).
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.alarma import CodigoAlarma
from web.modelos.cita import esta_dentro_de_ventana, fecha_local
from web.modelos.garita import CausaRechazoGarita, DecisionGarita, ResultadoAutorizacion
from web.modelos.retencion import CausaRetencion
from web.modelos.turno import Turno
from web.repositorios.repositorio_ciclo_cita import RepositorioCicloCita
from web.repositorios.repositorio_citas import CitaConFranja, RepositorioCitas
from web.repositorios.repositorio_intentos import RepositorioIntentos
from web.repositorios.repositorio_inventario import RepositorioInventario
from web.repositorios.repositorio_levantes import LEVANTE_OTORGADO, RepositorioLevantes
from web.repositorios.repositorio_manifiestos import (
    ManifiestoVigente,
    RepositorioManifiestos,
)
from web.repositorios.repositorio_plazas import RepositorioPlazas
from web.repositorios.repositorio_vehiculos import RepositorioVehiculos
from web.servicios.emisor_alarmas import EmisorAlarmas
from web.servicios.puertos import PublicadorLogica
from web.servicios.servicio_retenciones import ServicioRetenciones
from web.servicios.servicio_trabajos import ServicioTrabajos
from web.servicios.servicio_turnos import ServicioTurnos
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)


class ServicioGarita:
    """Cadena §9.4 completa; el núcleo convierte la decisión en AUT (§4.4)."""

    def __init__(
        self,
        vehiculos: RepositorioVehiculos,
        manifiestos: RepositorioManifiestos,
        levantes: RepositorioLevantes,
        citas: RepositorioCitas,
        ciclo_citas: RepositorioCicloCita,
        plazas: RepositorioPlazas,
        intentos: RepositorioIntentos,
        inventario: RepositorioInventario,
        maquina: ServicioTurnos,
        retenciones: ServicioRetenciones,
        trabajos: ServicioTrabajos,
        publicador: PublicadorLogica,
        fabrica_instante: Callable[[], datetime],
        alarmas: EmisorAlarmas,
    ) -> None:
        self._vehiculos = vehiculos
        self._manifiestos = manifiestos
        self._levantes = levantes
        self._citas = citas
        self._ciclo_citas = ciclo_citas
        self._plazas = plazas
        self._intentos = intentos
        self._inventario = inventario
        self._maquina = maquina
        self._retenciones = retenciones
        self._trabajos = trabajos
        self._publicador = publicador
        self._fabrica_instante = fabrica_instante
        self._alarmas = alarmas

    def validar_identificacion(
        self, identificador: str, seq: int | None, ts: str
    ) -> DecisionGarita:
        """Ejecuta la cadena de §9.4 para una identificación GAR y registra el desenlace."""
        vehiculo = self._vehiculos.buscar_por_identificador(identificador)
        if vehiculo is None:
            return self._rechazar(
                identificador,
                CausaRechazoGarita.VEHICULO_DESCONOCIDO,
                ts,
                detalle=f"identificador '{identificador}' no registrado",
            )
        manifiesto = self._elegir_manifiesto(vehiculo.transportista_id)
        if manifiesto is None:
            return self._rechazar(
                identificador,
                CausaRechazoGarita.SIN_MANIFIESTO,
                ts,
                vehiculo_id=vehiculo.id,
                detalle=f"sin manifiesto pendiente para '{identificador}'",
            )
        levante = self._levantes.de_manifiesto(manifiesto.id)
        if levante is None or levante.estado != LEVANTE_OTORGADO:
            causa = (
                CausaRechazoGarita.LEVANTE_RETENIDO
                if levante is not None and levante.estado == "retenida"
                else CausaRechazoGarita.SIN_LEVANTE
            )
            estado_texto = levante.estado if levante is not None else "sin_solicitud"
            return self._rechazar(
                identificador,
                causa,
                ts,
                vehiculo_id=vehiculo.id,
                detalle=f"levante del manifiesto {manifiesto.id} en estado '{estado_texto}'",
            )
        cita = self._cita_presentable(manifiesto.id)
        if cita is None:
            return self._rechazar(
                identificador,
                CausaRechazoGarita.SIN_CITA,
                ts,
                vehiculo_id=vehiculo.id,
                detalle=f"sin cita programada ni vencida hoy para el manifiesto {manifiesto.id}",
            )
        return self._autorizar(identificador, vehiculo.id, manifiesto, cita, levante.canal, seq, ts)

    # ------------------------------------------------------------- autorizar

    def _autorizar(
        self,
        identificador: str,
        vehiculo_id: int,
        manifiesto: ManifiestoVigente,
        cita: CitaConFranja,
        canal_levante: str | None,
        seq: int | None,
        ts: str,
    ) -> DecisionGarita:
        """Última verificación (riesgo vs plaza), creación del turno y RT04 si toca."""
        dentro = esta_dentro_de_ventana(
            cita.franja_fecha, cita.franja_inicio, cita.franja_fin, self._fabrica_instante()
        )
        canal_rojo = canal_levante == "rojo"
        riesgo_retencion = (not dentro) or canal_rojo
        if riesgo_retencion and not self._plazas.hay_libre():
            return self._rechazar(
                identificador,
                CausaRechazoGarita.PARQUEO_LLENO,
                ts,
                vehiculo_id=vehiculo_id,
                detalle=f"riesgo de retención (canal={canal_levante or 'verde'}, "
                f"ventana={'dentro' if dentro else 'fuera'}) con el parqueo lleno",
            )
        turno = self._crear_turno(vehiculo_id, manifiesto, cita.id, dentro, canal_rojo, ts, seq)
        decision = DecisionGarita(
            resultado=ResultadoAutorizacion.AUTORIZADO,
            turno_id=turno.id,
            identificador_vehiculo=identificador,
            tipo_op=manifiesto.tipo_op,
            peso_declarado_g=manifiesto.peso_declarado_g,
            tolerancia_pct=manifiesto.tolerancia_pct,
            canal="rojo" if canal_rojo else "verde",
            posicion_asignada=turno.posicion_patio,
            nivel_asignado=turno.nivel,
            retener_al_ingreso=not dentro,
            manifiesto_id=manifiesto.id,
            cita_id=cita.id,
        )
        if not dentro:
            # Fuera de ventana con plaza disponible NO es rechazo: RT04 (§9.4, §11.1).
            self._retenciones.retener(
                turno,
                CausaRetencion.RT04,
                "garita",
                peso_declarado_g=manifiesto.peso_declarado_g,
                observacion="Llegada fuera de ventana",
            )
        REGISTRO.info(
            "Garita: turno %d autorizado para '%s' (manifiesto %d, ventana %s)",
            turno.id,
            identificador,
            manifiesto.id,
            "dentro" if dentro else "fuera",
        )
        return decision

    def _crear_turno(
        self,
        vehiculo_id: int,
        manifiesto: ManifiestoVigente,
        cita_id: int,
        dentro: bool,
        canal_rojo: bool,
        ts: str,
        seq: int | None = None,
    ) -> Turno:
        """Crea el turno, reserva la posición (depósito) y planifica trabajos (§12.3)."""
        posicion: str | None = None
        nivel: int | None = None
        if manifiesto.tipo_op == "DEPOSITO":
            posicion, nivel = self._trabajos.asignar_celda_para_deposito()
            self._inventario.reservar(posicion)
        turno = self._maquina.crear_en_garita(
            vehiculo_id=vehiculo_id,
            manifiesto_id=manifiesto.id,
            cita_id=cita_id,
            tipo_op=manifiesto.tipo_op,
            canal="rojo" if canal_rojo else "verde",
            dentro_de_ventana=dentro,
            creado_en=ts or marca_utc(self._fabrica_instante()),
            seq=seq,
        )
        if posicion is not None and nivel is not None:
            self._maquina.actualizar_posicion(turno.id, posicion, nivel)
            self._maquina.registrar_evento(
                turno,
                tipo="patio.reservado",
                descripcion=f"Posición {posicion}/N{nivel} reservada para el depósito",
                valores={"posicion": posicion, "nivel": nivel},
                origen="servidor",
            )
            turno = self._maquina.buscar_turno(turno.id) or turno
        self._citas.marcar_ventana(cita_id, dentro)
        self._trabajos.planificar_para_turno(turno, manifiesto.contenedor_id, ts)
        return turno

    # -------------------------------------------------------------- rechazar

    def _rechazar(
        self,
        identificador: str,
        causa: CausaRechazoGarita,
        ts: str,
        vehiculo_id: int | None = None,
        detalle: str = "",
    ) -> DecisionGarita:
        """Registra el intento con su causa; no crea turno (§8.2 regla 1, §9.4).

        ``PARQUEO_LLENO`` es además riesgo de retención sin ramal: genera AL11
        persistida y publicada (§9.4, §10.1 paso 6, §13.1); el resto de causas
        documentales no alarman.
        """
        self._intentos.registrar(ts, identificador, vehiculo_id, causa.value, detalle)
        if causa is CausaRechazoGarita.PARQUEO_LLENO:
            self._alarmar_al11(identificador, detalle, ts)
        REGISTRO.warning(
            "Garita: ingreso rechazado (%s) para '%s': %s", causa.value, identificador, detalle
        )
        return DecisionGarita(
            resultado=ResultadoAutorizacion.RECHAZADO,
            causa=causa,
            identificador_vehiculo=identificador,
        )

    def _alarmar_al11(self, identificador: str, detalle: str, ts: str) -> None:
        """AL11 (media, origen servidor): parqueo lleno en el momento del riesgo (§13.1)."""
        datos: dict[str, object] = {"vehiculo": identificador, "detalle": detalle}
        self._alarmas.emitir(CodigoAlarma.AL11, datos, ts)

    # ---------------------------------------------------------------- helpers

    def _elegir_manifiesto(self, transportista_id: int) -> ManifiestoVigente | None:
        """El manifiesto a atender: con cita presentable primero; si no, el menor id [DEC]."""
        vigentes = self._manifiestos.vigentes_de_transportista(transportista_id)
        if not vigentes:
            return None
        for candidato in vigentes:
            if self._cita_presentable(candidato.id) is not None:
                return candidato
        return vigentes[0]

    def _cita_presentable(self, manifiesto_id: int) -> CitaConFranja | None:
        """Programada, o vencida hoy sin usar: llegar tarde es RT04, no rechazo (§11.1)."""
        hoy = fecha_local(self._fabrica_instante())
        return self._ciclo_citas.presentable_de_manifiesto(manifiesto_id, hoy)
