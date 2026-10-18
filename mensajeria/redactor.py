"""Texto de las nueve notificaciones automáticas (SPECS §15.3).

Cada tipo de ``notificacion.tipo`` tiene su redactor con el **contenido
mínimo** de la tabla §15.3. El ``payload`` viene de la BD, que escribió la
web: aun así se lee campo por campo con tolerancia (``—`` si falta) para que
un aviso incompleto salga igual y no bloquee la cola (P-5).
"""

from collections.abc import Callable, Mapping

from mensajeria.formato import duracion_legible, fecha_legible, peso_legible, recortar
from mensajeria.textos import CANAL_TEXTO, RESOLUCION_TEXTO, TIPO_OP_TEXTO
from web.modelos.cita import cierre_de_ventana
from web.modelos.notificacion import TipoNotificacion
from web.modelos.retencion import CAUSAS_DE_PESO, DEFINICIONES_CAUSA, CausaRetencion

Payload = Mapping[str, object]


def redactar(tipo: str, payload: Payload) -> str:
    """Texto plano del aviso; un tipo desconocido sale como aviso genérico."""
    try:
        redactor = _REDACTORES[TipoNotificacion(tipo)]
    except ValueError:
        return recortar(f"Aviso de la terminal: {tipo}.")
    return recortar(redactor(payload))


def ventana_legible(fecha: str, inicio: str, fin: str) -> str:
    """Franja con su ventana de presentación (§11.1 regla 6)."""
    return (
        f"{fecha_legible(fecha)}, de {inicio} a {fin} "
        f"(puedes presentarte hasta las {cierre_de_ventana(fin)})"
    )


def _campo(payload: Payload, clave: str) -> str:
    valor = payload.get(clave)
    return "—" if valor is None or valor == "" else str(valor)


def _ventana(payload: Payload) -> str:
    fecha, inicio, fin = (payload.get(clave) for clave in ("fecha", "inicio", "fin"))
    if not (isinstance(fecha, str) and isinstance(inicio, str) and isinstance(fin, str)):
        return "—"
    return ventana_legible(fecha, inicio, fin)


def _levante_otorgado(payload: Payload) -> str:
    canal = _campo(payload, "canal")
    texto = (
        f"✅ Levante otorgado para el contenedor {_campo(payload, 'contenedor')}.\n"
        f"Canal asignado: {CANAL_TEXTO.get(canal, canal)}.\n"
        "Ya puedes solicitar tu cita con /cita."
    )
    if canal == "rojo":
        texto += (
            "\n⚠️ Canal rojo: al ingresar, el vehículo será enviado a verificación "
            "en el parqueo de retención."
        )
    return texto


def _levante_retenido(payload: Payload) -> str:
    return (
        f"⛔ El levante del contenedor {_campo(payload, 'contenedor')} fue retenido "
        f"por la autoridad.\nMotivo: {_campo(payload, 'motivo')}"
    )


def _cita_asignada(payload: Payload) -> str:
    return (
        f"📅 Cita asignada para el contenedor {_campo(payload, 'contenedor')}.\n"
        f"Franja: {_ventana(payload)}."
    )


def _recordatorio(payload: Payload) -> str:
    return (
        f"⏰ Recordatorio: falta una hora para tu cita del contenedor "
        f"{_campo(payload, 'contenedor')}.\nFranja: {_ventana(payload)}."
    )


def _vehiculo_retenido(payload: Payload) -> str:
    codigo = _campo(payload, "causa")
    try:
        causa = CausaRetencion(codigo)
    except ValueError:
        descripcion = codigo
    else:
        descripcion = f"{DEFINICIONES_CAUSA[causa].descripcion} ({codigo})"
    texto = (
        f"🚧 Tu vehículo {_campo(payload, 'vehiculo')} fue retenido "
        f"(contenedor {_campo(payload, 'contenedor')}).\nCausa: {descripcion}."
    )
    if codigo in {c.value for c in CAUSAS_DE_PESO}:
        texto += (
            f"\nPeso declarado: {peso_legible(payload.get('peso_declarado_g'))}"
            f"\nPeso medido: {peso_legible(payload.get('peso_medido_g'))}"
            f"\nDiferencia: {peso_legible(payload.get('diferencia_g'))}"
            f" ({_campo(payload, 'diferencia_pct')} %)"
        )
    return texto + "\nEspera las instrucciones en el parqueo de retención."


def _retencion_resuelta(payload: Payload) -> str:
    resolucion = _campo(payload, "resolucion")
    texto = (
        f"🔓 Retención resuelta para el vehículo {_campo(payload, 'vehiculo')} "
        f"(contenedor {_campo(payload, 'contenedor')}).\n"
        f"Resolución: {RESOLUCION_TEXTO.get(resolucion, resolucion)}."
    )
    if resolucion == "CORREGIR" and "nuevo_peso_declarado_g" in payload:
        texto += f"\nNuevo peso declarado: {peso_legible(payload['nuevo_peso_declarado_g'])}."
    if resolucion == "RECHAZAR":
        texto += f"\nMotivo: {_campo(payload, 'motivo')}"
    return texto


def _cita_cancelada(payload: Payload) -> str:
    return (
        f"❌ La terminal canceló tu cita del contenedor {_campo(payload, 'contenedor')} "
        f"({_ventana(payload)}).\nPuedes solicitar otra con /cita."
    )


def _cita_reprogramada(payload: Payload) -> str:
    return (
        f"🔁 La terminal reprogramó tu cita del contenedor {_campo(payload, 'contenedor')}.\n"
        f"Ventana nueva: {_ventana(payload)}."
    )


def _turno_completado(payload: Payload) -> str:
    segundos = payload.get("tiempo_total_s")
    tiempo = duracion_legible(segundos) if isinstance(segundos, int | float) else "—"
    tipo_op = _campo(payload, "tipo_op")
    return (
        f"🏁 Operación completada: {TIPO_OP_TEXTO.get(tipo_op, tipo_op)} del contenedor "
        f"{_campo(payload, 'contenedor')} con el vehículo {_campo(payload, 'vehiculo')}.\n"
        f"Tiempo total en la terminal: {tiempo}."
    )


def _turno_anulado(payload: Payload) -> str:
    tipo_op = _campo(payload, "tipo_op")
    return (
        f"🚫 Turno anulado: {TIPO_OP_TEXTO.get(tipo_op, tipo_op)} del contenedor "
        f"{_campo(payload, 'contenedor')} con el vehículo {_campo(payload, 'vehiculo')}.\n"
        f"Causa: {_campo(payload, 'motivo')}\nEl vehículo debe dirigirse a la salida."
    )


_REDACTORES: dict[TipoNotificacion, Callable[[Payload], str]] = {
    TipoNotificacion.LEVANTE_OTORGADO: _levante_otorgado,
    TipoNotificacion.LEVANTE_RETENIDO: _levante_retenido,
    TipoNotificacion.CITA_ASIGNADA: _cita_asignada,
    TipoNotificacion.RECORDATORIO_CITA: _recordatorio,
    TipoNotificacion.VEHICULO_RETENIDO: _vehiculo_retenido,
    TipoNotificacion.RETENCION_RESUELTA: _retencion_resuelta,
    TipoNotificacion.CITA_CANCELADA: _cita_cancelada,
    TipoNotificacion.CITA_REPROGRAMADA: _cita_reprogramada,
    TipoNotificacion.TURNO_COMPLETADO: _turno_completado,
    TipoNotificacion.TURNO_ANULADO: _turno_anulado,
}
