"""Textos fijos del bot y rótulos legibles de los estados (SPECS §15.2; CODESTYLE A-5).

Una sola fuente para la lista de comandos: la usan ``/inicio``, ``/ayuda`` y
el menú que se registra en Telegram con ``setMyCommands`` (§15.4 paso 2).
Los mensajes se envían en texto plano (sin ``parse_mode``), así un ``<`` en
un motivo escrito por un usuario no rompe el mensaje (§15.4 «Formato»).
"""

from web.modelos.turno import EstadoTurno

COMANDOS: tuple[tuple[str, str], ...] = (
    ("inicio", "Presenta el servicio y la lista de comandos"),
    ("vincular", "Asocia esta cuenta a tu usuario: /vincular CODIGO"),
    ("cita", "Solicita una cita para un contenedor con levante"),
    ("miscitas", "Lista tus citas con su ventana y estado"),
    ("estado", "Consulta uno de tus contenedores: /estado CONTENEDOR"),
    ("misturnos", "Lista tus operaciones en curso"),
    ("ayuda", "Repite esta lista de comandos"),
)
"""Los 7 comandos obligatorios de §15.2 con su línea de descripción."""

COMANDO_START = "start"
"""Telegram lo envía al abrir el bot; se trata como ``/inicio`` (§15.4)."""


def lista_de_comandos() -> str:
    """Lista completa con una línea de descripción por comando (§15.2)."""
    return "\n".join(f"/{nombre} — {descripcion}" for nombre, descripcion in COMANDOS)


def texto_inicio(nombre_terminal: str, nombre_transportista: str) -> str:
    return (
        f"Hola, {nombre_transportista}. Este es el servicio de mensajería de "
        f"{nombre_terminal}.\n\nComandos disponibles:\n{lista_de_comandos()}"
    )


def texto_ayuda() -> str:
    return f"Comandos disponibles:\n{lista_de_comandos()}"


def texto_sin_vincular(nombre_terminal: str) -> str:
    """Respuesta única para cualquier comando de una cuenta no vinculada (§15.1 regla 5)."""
    return (
        f"Esta cuenta no está vinculada a {nombre_terminal}. Pide tu código de "
        "vinculación en la terminal y escribe:\n/vincular CODIGO"
    )


TEXTO_NO_RECONOCIDO = "Comando no reconocido. Escribe /ayuda para ver la lista de comandos."
TEXTO_VINCULAR_USO = "Escribe el código que te dio la terminal: /vincular CODIGO"
TEXTO_CODIGO_INVALIDO = (
    "El código no es válido o ya venció. Pide uno nuevo en la terminal "
    "(cada código sirve una sola vez y dura 60 minutos)."
)
TEXTO_DEMASIADOS_INTENTOS = (
    "Demasiados intentos de vinculación. Espera unos minutos y vuelve a intentarlo."
)
TEXTO_ESTADO_USO = "Indica el contenedor: /estado CONTENEDOR"
TEXTO_SIN_CARGA = "No tienes carga asociada a ese identificador."
"""§15.2: la misma respuesta para un contenedor ajeno o inexistente."""
TEXTO_SIN_CITABLES = (
    "No tienes contenedores con levante otorgado y sin cita. Cuando la autoridad "
    "otorgue un levante te avisaremos por aquí."
)
TEXTO_ELIGE_CONTENEDOR = "Elige el contenedor para la cita:"
TEXTO_ELIGE_FRANJA = "Elige la franja para {contenedor} (hora de la terminal):"
TEXTO_SIN_FRANJAS = "No hay franjas con capacidad en las próximas 24 horas. Intenta más tarde."
TEXTO_CONVERSACION_VENCIDA = "Esa solicitud ya no está activa. Escribe /cita para empezar de nuevo."
TEXTO_SIN_CITAS = "No tienes citas vigentes."
TEXTO_SIN_TURNOS = "No tienes operaciones en curso."
TEXTO_SOLO_PRIVADO = "Este servicio solo atiende chats privados."
TEXTO_ERROR_INTERNO = "No pudimos atender tu solicitud en este momento. Intenta de nuevo."

MOTIVO_RESERVA_TEXTO: dict[str, str] = {
    "SIN_CARGA": TEXTO_SIN_CARGA,
    "SIN_LEVANTE": "Ese contenedor ya no tiene el levante vigente o ya está en operación.",
    "CITA_VIGENTE": "Ese contenedor ya tiene una cita vigente.",
    "FRANJA_BLOQUEADA": "La terminal bloqueó esa franja. Elige otra:",
    "FRANJA_SIN_CAPACIDAD": "Esa franja se llenó mientras elegías. Elige otra:",
}
"""Rechazos de la reserva (§11.1, §11.3 paso 4) en lenguaje del transportista."""

TIPO_OP_TEXTO = {"DEPOSITO": "Depósito", "RETIRO": "Retiro"}

ESTADO_CITA_TEXTO = {
    "programada": "programada",
    "cumplida": "cumplida",
    "vencida": "vencida",
    "cancelada": "cancelada",
}
"""Estados exactos de §15.2 (/miscitas); el valor de la BD ya es el texto pedido."""

ESTADO_DOCUMENTAL_TEXTO = {
    "declarado": "Manifiesto declarado, sin declaración aduanera",
    "declaracion_presentada": "Declaración presentada",
    "levante_solicitado": "Levante solicitado, en revisión de la autoridad",
    "levante_otorgado": "Levante otorgado",
    "levante_retenido": "Levante retenido por la autoridad",
    "anulado": "Manifiesto anulado",
}

ESTADO_OPERATIVO_TEXTO = {
    "sin_turno": "Sin operación en curso",
    "en_curso": "Operación en curso",
    "completado": "Operación completada",
    "anulado": "Operación anulada",
}

CANAL_TEXTO = {
    "verde": "verde",
    "rojo": "rojo (el vehículo pasa a verificación)",
}

ESTACION_POR_ESTADO: dict[str, str] = {
    EstadoTurno.PROGRAMADO.value: "Por presentarse en garita",
    EstadoTurno.EN_GARITA.value: "Garita",
    EstadoTurno.EN_PESAJE_ENTRADA.value: "Báscula (pesaje de entrada)",
    EstadoTurno.EN_RUTA.value: "En ruta a la zona de transferencia",
    EstadoTurno.EN_TRANSFERENCIA.value: "Zona de transferencia (grúa)",
    EstadoTurno.EN_PESAJE_SALIDA.value: "Báscula (pesaje de salida)",
    EstadoTurno.EN_SALIDA.value: "Puerta de salida",
    EstadoTurno.RETENIDO.value: "Parqueo de retención",
}
"""El turno no guarda la estación: se deduce del estado (§8.1)."""

RESOLUCION_TEXTO = {
    "ACLARAR": "Aclarada: la operación continúa",
    "CORREGIR": "Corregida: se actualizó el peso declarado y la operación continúa",
    "RECHAZAR": "Rechazada: la operación se anula y el vehículo debe salir",
}
