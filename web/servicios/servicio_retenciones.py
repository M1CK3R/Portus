"""Retenciones y parqueo (SPECS §10): retener, asignar plaza y resolver.

Reglas aplicadas aquí: plaza libre de menor número con transacción (§10.1,
§10.6), ``AgujaParqueo`` al retener y ``AgujaLiberar`` al resolver (solo
cuando el vehículo pasó por el ramal; una retención tardía lo mantiene en su
punto con plaza lógica, A3 [DEC]), resoluciones con rol facultado (§10.2),
Corregir solo TERMINAL en RT01/RT02 (A12), Rechazar exige motivo y autoriza la
salida (§10.3), toda resolución notifica (§10.7) y RT05/RT06 se ordenan a mano
solo por su rol (A9). Una retención solo nace si la transición a ``Retenido``
es válida (§8.1): nunca se toma plaza para un turno que no puede retenerse.
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.retencion import (
    CausaRetencion,
    FilaBandejaRetencion,
    ResolucionRetencion,
    Retencion,
    compara_con_manifiesto,
    evidencia_de,
    puede_ordenar,
    puede_resolver,
    rol_facultado,
)
from web.modelos.turno import EstadoTurno, Turno, transicion_valida
from web.modelos.usuario import Rol, Usuario
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_retenciones import RepositorioRetenciones
from web.repositorios.repositorio_turnos import RepositorioTurnos
from web.servicios.avisos_retencion import AvisosRetencion
from web.servicios.servicio_parqueo import ServicioParqueo
from web.servicios.servicio_salida import ServicioSalida
from web.servicios.servicio_turnos import ErrorTransicion, ServicioTurnos
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

ESTACION_POR_ESTADO: dict[EstadoTurno, str] = {
    EstadoTurno.EN_GARITA: "garita",
    EstadoTurno.EN_PESAJE_ENTRADA: "pesaje_entrada",
    EstadoTurno.EN_PESAJE_SALIDA: "pesaje_salida",
    EstadoTurno.EN_SALIDA: "salida",
}
"""Dónde está el vehículo cuando se ordena RT05/RT06 (§10.2 «en cualquier momento»)."""


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


class ErrorCorreccionNoAplica(ErrorRetencion):
    """Corregir con un pesaje comparado contra la tara, no contra el manifiesto (A4, A12)."""


class ErrorOrdenRetencion(ErrorRetencion):
    """RT05/RT06 no aplica: causa, rol, turno o estado fuera de regla (§10.2, A9)."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


class ServicioRetenciones:
    """Ciclo de vida completo de una retención sobre el parqueo de 3 plazas."""

    def __init__(
        self,
        retenciones: RepositorioRetenciones,
        manifiestos: RepositorioManifiestos,
        turnos_repo: RepositorioTurnos,
        maquina: ServicioTurnos,
        salida: ServicioSalida,
        parqueo: ServicioParqueo,
        avisos: AvisosRetencion,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._retenciones = retenciones
        self._manifiestos = manifiestos
        self._turnos_repo = turnos_repo
        self._maquina = maquina
        self._salida = salida
        self._parqueo = parqueo
        self._avisos = avisos
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

        Lanza :class:`ErrorTransicion` **antes** de tocar el parqueo si §8.1 no
        permite ``Retenido`` desde el estado actual. Sin plaza libre la
        retención igual nace (el vehículo ya está dentro, A3 [DEC]) y genera
        AL11 (§10.1 paso 6); ``AgujaParqueo`` sale solo si el vehículo pasa
        por el ramal.
        """
        if not transicion_valida(turno.estado, EstadoTurno.RETENIDO):
            mensaje = (
                f"el turno {turno.id} en {turno.estado.value} no puede pasar a Retenido (§8.1)"
            )
            raise ErrorTransicion(mensaje)
        instante = marca_utc(self._fabrica_instante())
        plaza = self._parqueo.tomar_plaza(turno, causa, instante)
        retencion_id = self._retenciones.crear(
            turno.id, causa, estacion, plaza, peso_declarado_g, peso_medido_g, instante
        )
        retenida = self._buscar(retencion_id)
        valores: dict[str, object] = {"retencion": retencion_id, "causa": causa.value}
        valores["plaza"] = plaza
        if observacion:
            valores["observacion"] = observacion
        turno = self._maquina.transicionar(
            turno,
            EstadoTurno.RETENIDO,
            f"Retención {causa.value} en {estacion}",
            valores,
            origen="servidor",
        )
        if plaza is not None:
            self._parqueo.enviar_al_parqueo(plaza, turno.id, estacion)
        self._avisos.retencion_abierta(retenida, turno)
        REGISTRO.info(
            "Turno %d retenido: %s en %s (retención %d, plaza %s)",
            turno.id,
            causa.value,
            estacion,
            retencion_id,
            plaza,
        )
        return retenida

    def ordenar(
        self, turno_id: int, causa: CausaRetencion, usuario: Usuario, nota: str | None = None
    ) -> Retencion:
        """RT05 (AUTORIDAD, A9) o RT06 (TERMINAL) sobre un turno en curso (§10.2)."""
        if not puede_ordenar(usuario.rol, causa):
            raise ErrorOrdenRetencion(
                "ROL_NO_FACULTADO",
                f"el rol {usuario.rol.value} no puede ordenar {causa.value} (§10.2)",
            )
        turno = self._turnos_repo.buscar_por_id(turno_id)
        if turno is None:
            raise ErrorOrdenRetencion("TURNO_INEXISTENTE", f"no existe el turno {turno_id}")
        estacion = ESTACION_POR_ESTADO.get(turno.estado)
        if estacion is None:
            raise ErrorOrdenRetencion(
                "ESTADO_NO_RETENIBLE",
                f"el turno {turno_id} está en {turno.estado.value}; §8.1 solo admite "
                "Retenido desde EnGarita, EnPesajeEntrada, EnPesajeSalida o EnSalida",
            )
        observacion = f"Ordenada por {usuario.username}" + (f": {nota}" if nota else "")
        return self.retener(turno, causa, estacion, observacion=observacion)

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
        retencion, turno = self._validar_resolucion(retencion_id, resolucion, usuario, motivo)
        instante = marca_utc(self._fabrica_instante())
        if not self._retenciones.resolver(
            retencion_id, resolucion.value, motivo, observacion, usuario.id, instante
        ):
            raise ErrorRetencionResuelta(f"la retención {retencion_id} ya está resuelta")
        resuelta = self._buscar(retencion_id)
        if resolucion is ResolucionRetencion.CORREGIR:
            self._corregir_peso(retencion, turno, usuario, instante)

        if resolucion is ResolucionRetencion.RECHAZAR:
            self._parqueo.liberar_por_resolucion(retencion)
            self._rechazar(turno, motivo or "", retencion.id)
        elif self._falta_canal_rojo(retencion, turno):
            self._encadenar_rt03(retencion, turno)
        else:
            self._parqueo.liberar_por_resolucion(retencion)
            self._regresar(turno, retencion, resolucion, observacion)
        self._avisos.retencion_resuelta(resuelta, turno)
        REGISTRO.info(
            "Retención %d resuelta con %s por %s", retencion_id, resolucion.value, usuario.username
        )
        return resuelta

    def _validar_resolucion(
        self,
        retencion_id: int,
        resolucion: ResolucionRetencion,
        usuario: Usuario,
        motivo: str | None,
    ) -> tuple[Retencion, Turno]:
        """Todas las reglas §10.3 antes de escribir: nada cambia si alguna falla."""
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
        turno = self._turnos_repo.buscar_por_id(retencion.turno_id)
        if turno is None:
            mensaje = f"la retención {retencion_id} apunta al turno inexistente"
            raise RuntimeError(mensaje)
        if resolucion is ResolucionRetencion.CORREGIR and not compara_con_manifiesto(
            retencion.causa, turno.tipo_op
        ):
            raise ErrorCorreccionNoAplica(
                f"{retencion.causa.value} de un {turno.tipo_op} se comparó con la tara del "
                "vehículo: Corregir no aplica; use Aclarar o Rechazar"
            )
        return retencion, turno

    def _regresar(
        self,
        turno: Turno,
        retencion: Retencion,
        resolucion: ResolucionRetencion,
        observacion: str | None,
    ) -> None:
        """Aclarar/Corregir: el turno vuelve según el mapa de regreso (A2, §8.5)."""
        valores: dict[str, object] = {"retencion": retencion.id, "resolucion": resolucion.value}
        if observacion:
            valores["observacion"] = observacion
        self._maquina.transicionar(
            turno,
            self._maquina.estado_para_regreso(turno),
            f"Retención {retencion.causa.value} resuelta con {resolucion.value}",
            valores,
            origen="servidor",
        )

    def _falta_canal_rojo(self, retencion: Retencion, turno: Turno) -> bool:
        """RT01 aclarada en canal rojo: aún debe pasar por RT03 (§9.2, §10.2)."""
        return (
            retencion.causa is CausaRetencion.RT01
            and turno.canal == "rojo"
            and not self._retenciones.tiene_causa(turno.id, CausaRetencion.RT03)
        )

    def _encadenar_rt03(self, rt01: Retencion, turno: Turno) -> None:
        """El vehículo sigue en su plaza y la retención pasa a la autoridad (RT03)."""
        instante = marca_utc(self._fabrica_instante())
        rt03_id = self._retenciones.crear(
            turno.id,
            CausaRetencion.RT03,
            rt01.estacion,
            rt01.plaza,
            rt01.peso_declarado_g,
            rt01.peso_medido_g,
            instante,
        )
        rt03 = self._buscar(rt03_id)
        self._maquina.registrar_evento(
            turno,
            tipo="retencion.encadenada",
            descripcion=f"RT01 resuelta; sigue retenido por RT03 (canal rojo, retención {rt03_id})",
            valores={"retencion_previa": rt01.id, "retencion": rt03_id, "plaza": rt01.plaza},
            origen="servidor",
        )
        self._avisos.retencion_abierta(rt03, turno)

    def _rechazar(self, turno: Turno, motivo: str, retencion_id: int) -> None:
        """Rechazar: turno Anulado y salida autorizada sin completar (§10.3, §8.6.3)."""
        anulado = self._maquina.anular(
            turno, f"Retención {retencion_id} rechazada: {motivo}", "servidor"
        )
        self._salida.autorizar_salida_anulacion(anulado)

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

    # --------------------------------------------------------------- anular

    def anular_turno(self, turno_id: int, motivo: str) -> Turno:
        """Anulación manual de TERMINAL (§8.2 regla 4); con retención abierta, no (§10.3).

        Un turno retenido solo se anula con Rechazar por el rol facultado: si
        no, la TERMINAL cerraría de hecho una RT03/RT05 de la autoridad.
        """
        turno = self._turnos_repo.buscar_por_id(turno_id)
        if turno is None:
            raise ErrorOrdenRetencion("TURNO_INEXISTENTE", f"no existe el turno {turno_id}")
        abierta = self._retenciones.abierta_de_turno(turno_id)
        if abierta is not None:
            raise ErrorOrdenRetencion(
                "RETENCION_ABIERTA",
                f"el turno {turno_id} tiene abierta la retención {abierta.id} "
                f"({abierta.causa.value}); resuélvala con Rechazar",
            )
        anulado = self._maquina.anular(turno, motivo, "web")
        self._salida.autorizar_salida_anulacion(anulado)
        return anulado

    # --------------------------------------------------------------- bandeja

    def bandeja(
        self, rol: Rol, estado: str | None = None, causa: CausaRetencion | None = None
    ) -> list[FilaBandejaRetencion]:
        """Bandeja §14.3; AUTORIDAD solo ve las aduaneras RT03/RT05 (§7.4, §14.9)."""
        filas = self._retenciones.listar_bandeja(
            estado=estado,
            solo_aduaneras=rol is Rol.AUTORIDAD,
            causa=causa.value if causa is not None else None,
        )
        return [
            FilaBandejaRetencion(
                retencion=retencion,
                vehiculo=vehiculo,
                contenedor_id=contenedor,
                rol_facultado=rol_facultado(retencion.causa),
                evidencia=evidencia_de(retencion),
                corregible=compara_con_manifiesto(retencion.causa, tipo_op),
            )
            for retencion, vehiculo, contenedor, tipo_op in filas
        ]

    def _buscar(self, retencion_id: int) -> Retencion:
        retencion = self._retenciones.buscar_por_id(retencion_id)
        if retencion is None:
            mensaje = f"la retención {retencion_id} no se encontró tras escribirla"
            raise RuntimeError(mensaje)
        return retencion
