"""Núcleo de la lógica del turno en el servidor (carril Aplicación, Etapa 5).

Enruta los eventos del controlador hacia los servicios, **deduplica por
``id``** (§5.5, P-4: los eventos reenviados tras SYN no se aplican dos veces)
y lleva la bitácora de reconciliación (§3.3). Lógica sin hilos (T-3): el
consumidor MQTT de ``web/mqtt`` lo alimenta desde su hilo y las rutas Flask
usan los mismos servicios para la bandeja de retenciones.

Aquí vive también la fábrica ``crear()``: dueño único de las instancias
(CODESTYLE PY-7) para rutas y consumidor.
"""

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from web.configuracion.configuracion_logica import ConfiguracionLogica
from web.modelos.garita import DecisionGarita
from web.repositorios.conexion_bd import ConexionBd
from web.repositorios.repositorio_alarmas import RepositorioAlarmas
from web.repositorios.repositorio_ciclo_cita import RepositorioCicloCita
from web.repositorios.repositorio_citas import RepositorioCitas
from web.repositorios.repositorio_intentos import RepositorioIntentos
from web.repositorios.repositorio_inventario import RepositorioInventario
from web.repositorios.repositorio_levantes import RepositorioLevantes
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_notificaciones import RepositorioNotificaciones
from web.repositorios.repositorio_pesajes import RepositorioPesajes
from web.repositorios.repositorio_plazas import RepositorioPlazas
from web.repositorios.repositorio_reportes import RepositorioReportes
from web.repositorios.repositorio_retenciones import RepositorioRetenciones
from web.repositorios.repositorio_telemetria import RepositorioTelemetria
from web.repositorios.repositorio_trabajos import RepositorioTrabajos
from web.repositorios.repositorio_turnos import FilaTurno, ListadoTurnos, RepositorioTurnos
from web.repositorios.repositorio_vehiculos import RepositorioVehiculos
from web.servicios.avisos_retencion import AvisosRetencion
from web.servicios.emisor_alarmas import EmisorAlarmas
from web.servicios.muestreo_espera import MuestreoFilaEspera
from web.servicios.notificador import Notificador
from web.servicios.politica_asignacion import crear_politica
from web.servicios.puertos import PublicadorLogica
from web.servicios.servicio_alarmas import ServicioAlarmas
from web.servicios.servicio_citas import ServicioCitas
from web.servicios.servicio_comandos import ServicioComandos
from web.servicios.servicio_garita import ServicioGarita
from web.servicios.servicio_grua import ServicioGrua
from web.servicios.servicio_parqueo import ServicioParqueo
from web.servicios.servicio_patio import ServicioPatio
from web.servicios.servicio_pesajes import ServicioPesajes
from web.servicios.servicio_reportes import ServicioReportes
from web.servicios.servicio_retenciones import ServicioRetenciones
from web.servicios.servicio_salida import ServicioSalida
from web.servicios.servicio_trabajos import ServicioTrabajos
from web.servicios.servicio_turnos import ServicioTurnos
from web.servicios.vigilante_permanencia import VigilantePermanencia
from web.servicios.vigilante_retenciones import VigilanteRetenciones
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

TOPICO_SRV_TURNO = "portus/srv/turno"
TIPO_TURNO_AUTORIZACION = "turno.autorizacion"
TIPO_EVENTO_GARITA = "garita.identificacion"
TIPO_EVENTO_PESAJE = "pesaje.medicion"
TIPO_EVENTO_TRANSFERENCIA = "transferencia.evento"
TIPO_EVENTO_GRUA = "grua.paso"
TIPO_EVENTO_PATIO = "patio.cambio"
TIPO_EVENTO_SALIDA = "salida.verificacion"
TIPO_EVENTO_COMANDO_RESPUESTA = "comando.respuesta"
TIPO_EVENTO_ENLACE_ESTADO = "enlace.estado"
TIPO_EVENTO_LATIDO = "estado.latido"
TIPO_EVENTO_ALARMA_CONTROLADOR = "alarma.controlador"
TIPO_EVENTO_ALARMA_SERVIDOR = "alarma.servidor"
TIPOS_ALARMA_RECONCILIABLES = (TIPO_EVENTO_ALARMA_CONTROLADOR, TIPO_EVENTO_ALARMA_SERVIDOR)
"""Alarmas que el puente persistió en ``evento`` y la web pudo perderse caída (§3.3)."""

POSICIONES_POR_OMISION = ("P1", "P2", "P3", "P4")
"""Semilla por omisión del patio lineal; el catálogo real vive en la BD (§19.3)."""


@dataclass
class ContadoresLogica:
    """Contadores de la bitácora de reconciliación (§3.3)."""

    eventos_aplicados: int = 0
    eventos_duplicados: int = 0
    comandos_enviados: int = 0


class NucleoLogica:
    """Consumidor puro de eventos: enruta, deduplica y reconcilia (§5.5, §3.3)."""

    def __init__(
        self,
        servicios: "ServiciosLogica",
        posiciones: tuple[str, ...],
        fabrica_cmd_id: Callable[[], str],
    ) -> None:
        self._s = servicios
        self._posiciones = posiciones
        self._fabrica_cmd_id = fabrica_cmd_id
        self.contadores = ContadoresLogica()
        self._enlace_activo_previo = True

    # ------------------------------------------------- lecturas para la API

    @property
    def maquina(self) -> ServicioTurnos:
        return self._s.maquina

    @property
    def turnos_repo(self) -> RepositorioTurnos:
        return self._s.turnos_repo

    @property
    def retenciones(self) -> RepositorioRetenciones:
        return self._s.retenciones

    @property
    def retenciones_svc(self) -> ServicioRetenciones:
        return self._s.retenciones_svc

    @property
    def salida(self) -> ServicioSalida:
        return self._s.salida

    @property
    def parqueo_svc(self) -> ServicioParqueo:
        """Plazas del ramal: estado para el sinóptico y «Liberar parqueo» (§6.3, §14.1)."""
        return self._s.parqueo_svc

    @property
    def trabajos_svc(self) -> ServicioTrabajos:
        return self._s.trabajos_svc

    @property
    def vigilante_retenciones(self) -> VigilanteRetenciones:
        """AL12 de la tarea periódica del proceso web (§13.1)."""
        return self._s.vigilante_retenciones

    @property
    def vigilante_permanencia(self) -> VigilantePermanencia:
        """AL13 de la tarea periódica del proceso web (§12.2, §13.1)."""
        return self._s.vigilante_permanencia

    @property
    def garita(self) -> ServicioGarita:
        return self._s.garita

    @property
    def patio(self) -> ServicioPatio:
        return self._s.patio

    @property
    def alarmas_svc(self) -> ServicioAlarmas:
        return self._s.alarmas_svc

    @property
    def citas_svc(self) -> ServicioCitas:
        return self._s.citas_svc

    @property
    def notificador(self) -> Notificador:
        return self._s.notificador

    @property
    def grua_svc(self) -> ServicioGrua:
        return self._s.grua_svc

    @property
    def reportes_svc(self) -> ServicioReportes:
        return self._s.reportes_svc

    @property
    def comandos_svc(self) -> ServicioComandos:
        return self._s.comandos_svc

    @property
    def plazas(self) -> RepositorioPlazas:
        """Repositorio de plazas del parqueo para el sinóptico (§14.1)."""
        return self._s.plazas

    @property
    def reportes_repo(self) -> RepositorioReportes:
        return self._s.reportes_repo

    def listado_turnos(self, estados: tuple[str, ...]) -> list[FilaTurno]:
        """Filas del listado de la pestaña Turnos (§14.2)."""
        return self._s.listado.listar(estados=estados)

    @property
    def listado(self) -> ListadoTurnos:
        """Listado de turnos con filtros para la pestaña Turnos (§14.2)."""
        return self._s.listado

    # --------------------------------------------------------------- MQTT in

    def atender_mensaje(self, topico: str, datos: bytes) -> None:
        """Valida el envoltorio (PY-2), deduplica por id (P-4) y enruta por tipo."""
        mensaje = _parsear_envoltorio(topico, datos)
        if mensaje is None:
            return
        id_mensaje, ts, tipo, seq, contenido = mensaje
        if not self._marcar_procesado(id_mensaje, ts):
            self.contadores.eventos_duplicados += 1
            return
        datos_evento = _datos_dict(contenido)
        # Despacho uniforme: cada manejador firma (datos, seq, ts); los tipos
        # propios del servidor y los aún sin lógica se descartan en silencio.
        manejador = _DESPACHO_EVENTOS.get(tipo)
        if manejador is not None:
            manejador(self, datos_evento, seq, ts)
        self.contadores.eventos_aplicados += 1

    # Manejadores con firma uniforme (datos, seq, ts); el enrutado vive en
    # _DESPACHO_EVENTOS para mantener atender_mensaje lineal (C901).

    def _evento_garita(self, datos: dict[str, object], seq: int | None, ts: str) -> None:
        self._atender_garita(datos, seq, ts)

    def _evento_pesaje(self, datos: dict[str, object], seq: int | None, ts: str) -> None:
        self._s.pesajes_svc.procesar_pesaje(
            str(datos.get("veh", "")),
            _entero(datos.get("peso_g")),
            _entero(datos.get("muestras")),
            bool(datos.get("meseta")),
            seq,
        )
        _ = ts

    def _evento_transferencia(self, datos: dict[str, object], seq: int | None, ts: str) -> None:
        self._s.trabajos_svc.procesar_transferencia(
            str(datos.get("evento", "")), str(datos.get("veh", "")), seq
        )
        _ = ts

    def _evento_grua(self, datos: dict[str, object], seq: int | None, ts: str) -> None:
        self._s.trabajos_svc.procesar_paso_grua(
            str(datos.get("paso", "")),
            str(datos.get("resultado", "")),
            str(datos.get("contenedor", "")),
            seq,
            ts,
        )

    def _evento_patio(self, datos: dict[str, object], seq: int | None, ts: str) -> None:
        self._s.patio.procesar_cambio_posicion(
            str(datos.get("posicion", "")),
            _entero(datos.get("nivel")),
            str(datos.get("contenedor", "")),
            str(datos.get("estado", "")),
            ts,
        )
        _ = seq

    def _evento_salida(self, datos: dict[str, object], seq: int | None, ts: str) -> None:
        # El puente renombra el campo serial ``res`` a ``resultado`` al publicar
        # (mensajes_mqtt.py: SAL.res → resultado); se aceptan ambos por si el
        # evento viene de una fuente que aún usa ``res``.
        resultado = datos.get("resultado") or datos.get("res") or ""
        self._s.salida.procesar_salida(
            str(datos.get("veh", "")),
            str(resultado),
            _texto(datos.get("causa")),
            seq,
        )
        _ = ts

    def _evento_respuesta_comando(self, datos: dict[str, object], seq: int | None, ts: str) -> None:
        self._atender_respuesta_comando(datos)
        _ = (seq, ts)

    def _evento_estado_enlace(self, datos: dict[str, object], seq: int | None, ts: str) -> None:
        self._atender_estado_enlace(datos)
        _ = (seq, ts)

    def _evento_latido(self, datos: dict[str, object], seq: int | None, ts: str) -> None:
        """El latido EST alimenta la disponibilidad de comandos (§6.3) y la métrica 6 (A15)."""
        self._s.comandos_svc.actualizar_estado(
            str(datos.get("modo", "")), str(datos.get("grua", "")), ts
        )
        self._s.muestreo_espera.registrar(datos.get("vehiculos_en_espera"), ts)
        _ = seq

    def _evento_alarma_controlador(
        self, datos: dict[str, object], seq: int | None, ts: str
    ) -> None:
        self._s.alarmas_svc.procesar_alarma_controlador(datos, ts)
        _ = seq

    def _evento_alarma_servidor(self, datos: dict[str, object], seq: int | None, ts: str) -> None:
        self._s.alarmas_svc.procesar_alarma_enlace(datos, ts)
        _ = seq

    def reconciliar_alarmas(self, desde_ts: str) -> int:
        """Aplica las alarmas que el puente persistió mientras la web no escuchaba.

        E14: si la web arranca después que el puente, la AL01 retroactiva y
        los ``ALM`` del controlador ya pasaron por MQTT; el puente los guardó
        en ``evento`` y aquí se reinyectan. La deduplicación por ``id`` (P-4)
        descarta los que la web sí había atendido. Devuelve cuántos aplicó.
        """
        with self._s.bd.candado:
            filas = self._s.bd.conexion.execute(
                "SELECT id, ts, origen, tipo, seq, datos, topico FROM evento "
                "WHERE tipo IN (?, ?) AND ts >= ? ORDER BY ts",
                (*TIPOS_ALARMA_RECONCILIABLES, desde_ts),
            ).fetchall()
        aplicados_antes = self.contadores.eventos_aplicados
        for fila in filas:
            envoltorio = {
                "id": fila[0],
                "ts": fila[1],
                "origen": fila[2],
                "tipo": fila[3],
                "seq": fila[4],
                "datos": json.loads(str(fila[5])),
            }
            self.atender_mensaje(str(fila[6]), json.dumps(envoltorio).encode("utf-8"))
        aplicados = self.contadores.eventos_aplicados - aplicados_antes
        REGISTRO.info("Reconciliación de alarmas desde %s: %d aplicadas", desde_ts, aplicados)
        return aplicados

    # ------------------------------------------------------------publicación

    def publicar_autorizacion(self, decision: DecisionGarita) -> None:
        """Envía AUT al controlador vía ``portus/srv/turno`` (§4.4, A7 [DEC])."""
        datos: dict[str, object] = {
            "resultado": decision.resultado.value,
            "veh": decision.identificador_vehiculo,
            "turno": decision.turno_id,
            "tipo_op": decision.tipo_op,
            "peso_decl_g": decision.peso_declarado_g,
            "tol_pct": decision.tolerancia_pct,
            "canal": decision.canal,
            "pos_asignada": decision.posicion_asignada,
            "nivel": decision.nivel_asignado,
            "causa": decision.causa.value if decision.causa is not None else None,
        }
        self._s.publicador.publicar(TOPICO_SRV_TURNO, TIPO_TURNO_AUTORIZACION, datos)

    # ----------------------------------------------------------------- rutas

    def _atender_garita(self, datos: dict[str, object], seq: int | None, ts: str) -> None:
        decision = self._s.garita.validar_identificacion(str(datos.get("veh", "")), seq, ts)
        self.publicar_autorizacion(decision)
        # La talanquera abre solo con AUT AUTORIZADO (§4.4); con riesgo y plaza
        # la retención RT04 ya salió desde validar_identificación.
        _ = decision

    def _atender_respuesta_comando(self, datos: dict[str, object]) -> None:
        """ACK aplica bloqueos y liberaciones pendientes; NAK → AL14 persistida (§6.2, §13.1).

        El estado de la BD sigue al controlador: patio y plazas solo cambian
        cuando este acepta el comando (penalización §23.3 si se ejecuta pese
        a su condición de rechazo).
        """
        estado = str(datos.get("estado", ""))
        sintetica = bool(datos.get("sintetica", False))
        cmd_id = _texto(datos.get("cmd_id")) or ""
        self._s.patio.aplicar_respuesta_comando(cmd_id, estado, sintetica)
        self._s.parqueo_svc.aplicar_respuesta_comando(cmd_id, estado, sintetica)
        if estado != "NAK":
            return
        # §6.2 regla 2 y §4.5: todo rechazo, también el sintético SIN_RESPUESTA
        # del puente (comando fallido), genera AL14 con la causa exacta.
        self._s.alarmas_svc.procesar_comando_rechazado(datos)

    def _atender_estado_enlace(self, datos: dict[str, object]) -> None:
        """Reconciliación §3.3: al restablecerse el enlace se anota el resumen en la bitácora."""
        activo = str(datos.get("enlace", "")) == "activo"
        if activo and not self._enlace_activo_previo:
            self._registrar_reconciliacion("enlace_restablecido")
        self._enlace_activo_previo = activo

    def _marcar_procesado(self, id_mensaje: str, ts: str) -> bool:
        """True la primera vez que se ve el id; False en retransmisiones (§5.5)."""
        with self._s.bd.candado:
            cursor = self._s.bd.conexion.execute(
                "INSERT OR IGNORE INTO evento_procesado (id, ts) VALUES (?, ?)",
                (id_mensaje, ts),
            )
            self._s.bd.conexion.commit()
        return cursor.rowcount > 0

    def _registrar_reconciliacion(self, motivo: str) -> None:
        """Resumen de eventos aplicados/duplicados en la telemetría (§3.3 [DEC])."""
        instante = self._s.fabrica_instante()
        resumen = {
            "motivo": motivo,
            "eventos_aplicados": self.contadores.eventos_aplicados,
            "eventos_duplicados": self.contadores.eventos_duplicados,
        }
        id_unico = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"reconciliacion:{marca_utc(instante)}:{motivo}")
        )
        self._s.telemetria.registrar(
            id_unico, marca_utc(instante), "reconciliacion", json.dumps(resumen, ensure_ascii=False)
        )
        self.contadores.eventos_aplicados = 0
        self.contadores.eventos_duplicados = 0
        REGISTRO.info("Reconciliación registrada (%s): %s", motivo, resumen)


@dataclass(frozen=True)
class ServiciosLogica:
    """Todo lo que la lógica usa, construido una sola vez (PY-7)."""

    bd: ConexionBd
    publicador: PublicadorLogica
    fabrica_instante: Callable[[], datetime]
    vehiculos: RepositorioVehiculos
    manifiestos: RepositorioManifiestos
    levantes: RepositorioLevantes
    citas: RepositorioCitas
    plazas: RepositorioPlazas
    intentos: RepositorioIntentos
    inventario: RepositorioInventario
    turnos_repo: RepositorioTurnos
    pesajes: RepositorioPesajes
    retenciones: RepositorioRetenciones
    trabajos: RepositorioTrabajos
    alarmas: RepositorioAlarmas
    emisor_alarmas: EmisorAlarmas
    notificaciones: RepositorioNotificaciones
    notificador: Notificador
    telemetria: RepositorioTelemetria
    muestreo_espera: MuestreoFilaEspera
    reportes_repo: RepositorioReportes
    maquina: ServicioTurnos
    garita: ServicioGarita
    retenciones_svc: ServicioRetenciones
    parqueo_svc: ServicioParqueo
    trabajos_svc: ServicioTrabajos
    patio: ServicioPatio
    pesajes_svc: ServicioPesajes
    salida: ServicioSalida
    listado: ListadoTurnos
    alarmas_svc: ServicioAlarmas
    citas_svc: ServicioCitas
    grua_svc: ServicioGrua
    reportes_svc: ServicioReportes
    comandos_svc: ServicioComandos
    vigilante_retenciones: VigilanteRetenciones
    vigilante_permanencia: VigilantePermanencia


def crear(
    bd: ConexionBd,
    publicador: PublicadorLogica,
    fabrica_instante: Callable[[], datetime],
    configuracion: ConfiguracionLogica | None = None,
    fabrica_cmd_id: Callable[[], str] | None = None,
) -> NucleoLogica:
    """Construye la lógica completa sobre la base compartida (CODESTYLE A-2)."""
    config = configuracion or ConfiguracionLogica()
    manifiestos = RepositorioManifiestos(bd)
    vehiculos = RepositorioVehiculos(bd)
    levantes = RepositorioLevantes(bd)
    citas = RepositorioCitas(bd)
    ciclo_citas = RepositorioCicloCita(bd)
    plazas = RepositorioPlazas(bd)
    intentos = RepositorioIntentos(bd)
    inventario = RepositorioInventario(bd)
    turnos_repo = RepositorioTurnos(bd)
    pesajes = RepositorioPesajes(bd)
    retenciones = RepositorioRetenciones(bd)
    trabajos = RepositorioTrabajos(bd)
    alarmas = RepositorioAlarmas(bd)
    notificaciones = RepositorioNotificaciones(bd)
    telemetria = RepositorioTelemetria(bd)
    emisor = EmisorAlarmas(alarmas, publicador, fabrica_instante)
    notificador = Notificador(notificaciones, publicador, fabrica_instante)
    maquina = ServicioTurnos(
        turnos_repo, manifiestos, citas, ciclo_citas, publicador, fabrica_instante
    )
    politica = crear_politica(config.politica_asignacion)
    trabajos_svc = ServicioTrabajos(
        trabajos,
        inventario,
        turnos_repo,
        vehiculos,
        maquina,
        politica,
        _posiciones_de_bd(bd),
        publicador,
        fabrica_instante,
    )
    salida = ServicioSalida(
        vehiculos,
        turnos_repo,
        manifiestos,
        citas,
        notificador,
        emisor,
        maquina,
        trabajos_svc,
        publicador,
        fabrica_instante,
    )
    avisos = AvisosRetencion(vehiculos, manifiestos, notificador, publicador)
    parqueo_svc = ServicioParqueo(plazas, retenciones, emisor, avisos, publicador)
    retenciones_svc = ServicioRetenciones(
        retenciones,
        manifiestos,
        turnos_repo,
        maquina,
        salida,
        parqueo_svc,
        avisos,
        fabrica_instante,
    )
    patio = ServicioPatio(inventario, publicador)
    pesajes_svc = ServicioPesajes(
        vehiculos,
        manifiestos,
        turnos_repo,
        pesajes,
        maquina,
        retenciones_svc,
        publicador,
        fabrica_instante,
        emisor,
    )
    listado = ListadoTurnos(bd)
    garita = ServicioGarita(
        vehiculos,
        manifiestos,
        levantes,
        citas,
        ciclo_citas,
        plazas,
        intentos,
        inventario,
        maquina,
        retenciones_svc,
        trabajos_svc,
        publicador,
        fabrica_instante,
        emisor,
    )
    reportes_repo = RepositorioReportes(bd)
    alarmas_svc = ServicioAlarmas(alarmas, emisor, publicador, fabrica_instante)
    citas_svc = ServicioCitas(
        citas, ciclo_citas, manifiestos, notificador, publicador, fabrica_instante
    )
    grua_svc = ServicioGrua(trabajos, alarmas, publicador, fabrica_instante)
    reportes_svc = ServicioReportes(
        turnos_repo,
        retenciones,
        trabajos,
        ciclo_citas,
        telemetria,
        reportes_repo,
        config.politica_asignacion,
        fabrica_instante,
    )
    comandos_svc = ServicioComandos(publicador)
    servicios = ServiciosLogica(
        bd=bd,
        publicador=publicador,
        fabrica_instante=fabrica_instante,
        vehiculos=vehiculos,
        manifiestos=manifiestos,
        levantes=levantes,
        citas=citas,
        plazas=plazas,
        intentos=intentos,
        inventario=inventario,
        turnos_repo=turnos_repo,
        pesajes=pesajes,
        retenciones=retenciones,
        trabajos=trabajos,
        alarmas=alarmas,
        emisor_alarmas=emisor,
        notificaciones=notificaciones,
        notificador=notificador,
        telemetria=telemetria,
        muestreo_espera=MuestreoFilaEspera(telemetria),
        reportes_repo=reportes_repo,
        maquina=maquina,
        garita=garita,
        retenciones_svc=retenciones_svc,
        parqueo_svc=parqueo_svc,
        trabajos_svc=trabajos_svc,
        patio=patio,
        pesajes_svc=pesajes_svc,
        salida=salida,
        listado=listado,
        alarmas_svc=alarmas_svc,
        citas_svc=citas_svc,
        grua_svc=grua_svc,
        reportes_svc=reportes_svc,
        comandos_svc=comandos_svc,
        vigilante_retenciones=VigilanteRetenciones(retenciones, alarmas, emisor, fabrica_instante),
        vigilante_permanencia=VigilantePermanencia(inventario, alarmas, emisor, fabrica_instante),
    )
    return NucleoLogica(servicios, _posiciones_de_bd(bd), fabrica_cmd_id or _uuid_aleatorio)


# Enrutado de eventos del controlador (§5.2): tipo → manejador con firma
# uniforme (datos, seq, ts). Los tipos del servidor y los aún sin lógica de
# la Etapa 5 no figuran y se descartan en atender_mensaje (P-5).
_DESPACHO_EVENTOS: dict[str, Callable[[NucleoLogica, dict[str, object], int | None, str], None]] = {
    TIPO_EVENTO_GARITA: NucleoLogica._evento_garita,
    TIPO_EVENTO_PESAJE: NucleoLogica._evento_pesaje,
    TIPO_EVENTO_TRANSFERENCIA: NucleoLogica._evento_transferencia,
    TIPO_EVENTO_GRUA: NucleoLogica._evento_grua,
    TIPO_EVENTO_PATIO: NucleoLogica._evento_patio,
    TIPO_EVENTO_SALIDA: NucleoLogica._evento_salida,
    TIPO_EVENTO_COMANDO_RESPUESTA: NucleoLogica._evento_respuesta_comando,
    TIPO_EVENTO_ENLACE_ESTADO: NucleoLogica._evento_estado_enlace,
    TIPO_EVENTO_LATIDO: NucleoLogica._evento_latido,
    TIPO_EVENTO_ALARMA_CONTROLADOR: NucleoLogica._evento_alarma_controlador,
    TIPO_EVENTO_ALARMA_SERVIDOR: NucleoLogica._evento_alarma_servidor,
}


def _posiciones_de_bd(bd: ConexionBd) -> tuple[str, ...]:
    """Catálogo de posiciones del patio; si la BD está vacía siembra P1-P4 [DEC].

    La autosiembra del catálogo por omisión hace que la plataforma funcione en
    una instalación nueva sin depender del paso de la semilla; el catálogo
    real de la maqueta se define con ``crear_datos_semilla.py`` (§19.3).
    """
    with bd.candado:
        filas = bd.conexion.execute("SELECT id FROM posicion_patio ORDER BY id").fetchall()
        if not filas:
            for posicion in POSICIONES_POR_OMISION:
                bd.conexion.execute(
                    "INSERT OR IGNORE INTO posicion_patio (id, estado) VALUES (?, 'libre')",
                    (posicion,),
                )
            bd.conexion.commit()
            filas = bd.conexion.execute("SELECT id FROM posicion_patio ORDER BY id").fetchall()
    return tuple(str(fila[0]) for fila in filas)


def _parsear_envoltorio(
    topico: str, datos: bytes
) -> tuple[str, str, str, int | None, dict[str, object]] | None:
    """Valida el envoltorio §5.2 al entrar (PY-2); None si es inválido (P-5)."""
    try:
        contenido = json.loads(datos.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        REGISTRO.warning("Mensaje MQTT mal formado en %s: %s", topico, error)
        return None
    if not isinstance(contenido, dict):
        REGISTRO.warning("Mensaje MQTT sin objeto JSON en %s", topico)
        return None
    id_mensaje = contenido.get("id")
    ts = contenido.get("ts")
    tipo = contenido.get("tipo")
    if not isinstance(id_mensaje, str) or not isinstance(ts, str) or not isinstance(tipo, str):
        REGISTRO.warning("Mensaje MQTT sin id/ts/tipo válidos en %s", topico)
        return None
    seq = contenido.get("seq")
    return (id_mensaje, ts, tipo, seq if isinstance(seq, int) else None, contenido)


def _datos_dict(contenido: dict[str, object]) -> dict[str, object]:
    datos = contenido.get("datos", {})
    return cast(dict[str, object], datos) if isinstance(datos, dict) else {}


def _entero(valor: object) -> int:
    if isinstance(valor, bool):
        return int(valor)
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str) and valor.lstrip("-").isdigit():
        return int(valor)
    return 0


def _texto(valor: object) -> str | None:
    return valor if isinstance(valor, str) else None


def _uuid_aleatorio() -> str:
    return str(uuid.uuid4())
