"""Catálogo de las notificaciones automáticas al transportista (SPECS §15.3).

Las nueve notificaciones de la tabla §15.3 se guardan con uno de estos tipos
en ``notificacion.tipo`` y se publican como ``notificacion.<tipo>`` en el
tópico ``portus/srv/*`` de su dominio (§5.3). La 7 tiene dos variantes
(cancelada o reprogramada) y la de cierre se distingue de la de anulación,
así que hay diez tipos para nueve avisos.
"""

from enum import StrEnum

PREFIJO_TIPO_MQTT = "notificacion."
"""Los mensajes MQTT de aviso llevan ``tipo = notificacion.<TipoNotificacion>``."""


class TipoNotificacion(StrEnum):
    """Tipos exactos de ``notificacion.tipo``; el número es el de §15.3."""

    LEVANTE_OTORGADO = "levante_otorgado"  # 1
    LEVANTE_RETENIDO = "levante_retenido"  # 2
    CITA_ASIGNADA = "cita_asignada"  # 3
    RECORDATORIO_CITA = "recordatorio_cita"  # 4
    VEHICULO_RETENIDO = "vehiculo_retenido"  # 5
    RETENCION_RESUELTA = "retencion_resuelta"  # 6
    CITA_CANCELADA = "cita_cancelada"  # 7
    CITA_REPROGRAMADA = "cita_reprogramada"  # 7
    TURNO_COMPLETADO = "turno_completado"  # 8
    TURNO_ANULADO = "turno_anulado"  # 9


def tipo_mqtt(tipo: TipoNotificacion) -> str:
    """``tipo`` del envoltorio MQTT para esa notificación (§5.2)."""
    return f"{PREFIJO_TIPO_MQTT}{tipo.value}"
