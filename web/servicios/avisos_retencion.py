"""Avisos de una retención al transportista y al tablero (SPECS §10.7, §15.3 avisos 5 y 6).

Cada retención abierta o resuelta deja una notificación persistida para el
transportista propietario de la carga (el bot la despacha, Etapa 10) y publica
el cambio en ``portus/srv/retencion`` para el sinóptico y las bandejas.
"""

from web.modelos.notificacion import TipoNotificacion
from web.modelos.retencion import CAUSAS_DE_PESO, Retencion, evidencia_de
from web.modelos.turno import Turno
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_vehiculos import RepositorioVehiculos
from web.servicios.notificador import Notificador
from web.servicios.puertos import PublicadorLogica

TOPICO_SRV_RETENCION = "portus/srv/retencion"
TIPO_RETENCION_ABIERTA = "retencion.abierta"
TIPO_RETENCION_RESUELTA = "retencion.resuelta"
TIPO_PARQUEO_PLAZA = "parqueo.plaza"


class AvisosRetencion:
    """Notificaciones §10.7 y publicaciones de la bandeja y del parqueo."""

    def __init__(
        self,
        vehiculos: RepositorioVehiculos,
        manifiestos: RepositorioManifiestos,
        notificador: Notificador,
        publicador: PublicadorLogica,
    ) -> None:
        self._vehiculos = vehiculos
        self._manifiestos = manifiestos
        self._notificador = notificador
        self._publicador = publicador

    def retencion_abierta(self, retencion: Retencion, turno: Turno) -> None:
        """Aviso 5 «vehículo retenido»: vehículo, contenedor, causa y evidencia de peso."""
        payload: dict[str, object] = {
            "vehiculo": self.vehiculo_de(turno),
            "contenedor": self.contenedor_de(turno),
            "causa": retencion.causa.value,
        }
        evidencia = evidencia_de(retencion)
        if evidencia is not None:
            payload["peso_declarado_g"] = evidencia.peso_declarado_g
            payload["peso_medido_g"] = evidencia.peso_medido_g
            payload["diferencia_g"] = evidencia.diferencia_abs_g
            payload["diferencia_pct"] = evidencia.diferencia_pct
        self._notificar(turno, TipoNotificacion.VEHICULO_RETENIDO, payload)
        self._publicador.publicar(
            TOPICO_SRV_RETENCION, TIPO_RETENCION_ABIERTA, datos_retencion(retencion)
        )

    def retencion_resuelta(self, retencion: Retencion, turno: Turno) -> None:
        """Aviso 6 «retención resuelta»: nuevo peso si Corregir, motivo si Rechazar."""
        payload: dict[str, object] = {
            "vehiculo": self.vehiculo_de(turno),
            "contenedor": self.contenedor_de(turno),
            "resolucion": retencion.resolucion,
        }
        if retencion.resolucion == "CORREGIR" and retencion.causa in CAUSAS_DE_PESO:
            payload["nuevo_peso_declarado_g"] = retencion.peso_medido_g
        if retencion.resolucion == "RECHAZAR":
            payload["motivo"] = retencion.motivo
        self._notificar(turno, TipoNotificacion.RETENCION_RESUELTA, payload)
        self._publicador.publicar(
            TOPICO_SRV_RETENCION, TIPO_RETENCION_RESUELTA, datos_retencion(retencion)
        )

    def plaza(self, numero: int, turno_id: int | None) -> None:
        """Cambio de ocupación de una plaza para el sinóptico (§14.1)."""
        self._publicador.publicar(
            TOPICO_SRV_RETENCION, TIPO_PARQUEO_PLAZA, {"plaza": numero, "turno": turno_id}
        )

    def vehiculo_de(self, turno: Turno) -> str:
        vehiculo = self._vehiculos.buscar_por_id(turno.vehiculo_id)
        return vehiculo.identificador if vehiculo is not None else ""

    def contenedor_de(self, turno: Turno) -> str:
        manifiesto = self._manifiestos.buscar_por_id(turno.manifiesto_id)
        return manifiesto.contenedor_id if manifiesto is not None else ""

    def _notificar(self, turno: Turno, tipo: TipoNotificacion, payload: dict[str, object]) -> None:
        """Solo al transportista propietario de la carga (§15.3)."""
        manifiesto = self._manifiestos.buscar_por_id(turno.manifiesto_id)
        if manifiesto is None:
            mensaje = f"el turno {turno.id} apunta al manifiesto inexistente {turno.manifiesto_id}"
            raise RuntimeError(mensaje)
        self._notificador.notificar(
            TOPICO_SRV_RETENCION, manifiesto.transportista_id, tipo, payload
        )


def datos_retencion(retencion: Retencion) -> dict[str, object]:
    """Bloque ``datos`` de ``retencion.abierta`` / ``retencion.resuelta`` (§5.3)."""
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
        "creada_en": retencion.creada_en,
        "resuelta_en": retencion.resuelta_en,
    }
