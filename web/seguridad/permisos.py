"""Matriz de permisos aplicada en el servidor (SPECS §7.4, §7.5; CODESTYLE PY-3).

Todo endpoint declara su acción con ``@requiere_rol(...)``; ocultar un botón
no es control de permisos. Un intento no permitido se rechaza **en el
servidor** con ``403`` y un mensaje explícito con la forma del §7.5.1::

    {"error": "ACCION_NO_PERMITIDA", "mensaje": "El rol NAVIERA no puede ..."}

y cada rechazo se registra en ``auditoria_rechazo`` (§7.5.5).
"""

import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import ParamSpec, cast

import flask
from werkzeug.wrappers import Response

from web.modelos.usuario import Rol, Usuario
from web.repositorios.repositorio_auditoria import RepositorioAuditoria
from web.seguridad.sesion import usuario_en_sesion
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

ERROR_SIN_SESION = "SESION_REQUERIDA"
ERROR_ACCION_NO_PERMITIDA = "ACCION_NO_PERMITIDA"
ERROR_SESION_EXPIRADA = "SESION_EXPIRADA"
MENSAJE_SIN_SESION = "Inicie sesión para usar el servicio."

CLAVE_AUDITORIA = "repositorio_auditoria"
"""Clave bajo la que la aplicación publica el repositorio de auditoría."""

ParametrosVista = ParamSpec("ParametrosVista")
Respuesta = Response
"""Tipo de respuesta común: ``flask.Response`` hereda de él y las funciones
``redirect``/``jsonify`` de Flask devuelven algo asignable a este alias."""
Vista = Callable[..., Respuesta]


@dataclass(frozen=True)
class Accion:
    """Una acción de la matriz §7.4: quién puede y qué se le dice a los demás."""

    nombre: str
    roles_permitidos: frozenset[Rol]
    frase_rechazo: str


# Filas de la matriz §7.4 aplicadas en el servidor: 2 en la Etapa 4 y 4 en la
# Etapa 5 (turnos, gestión de turnos, bandeja de retenciones y resoluciones).
# Las demás NO son un faltante: el ROADMAP las asigna a etapas posteriores y
# cada una se agrega aquí como ``Accion`` cuando su endpoint existe —
#   Etapa 6  · ver sinóptico, agenda completa de citas, reporte de corrida
#              (paneles de comandos/alarmas completan su lógica en 8-9)
#   Etapa 7  · crear manifiesto, presentar declaración y solicitar levante,
#              otorgar o retener levante, asignar canal de selectivo,
#              consultar ubicación (NAVIERA/AGENTE/AUTORIDAD)
#   Etapa 8  · retenciones operativa y aduanera completas con su pestaña;
#              Retener turno RT05 desde Consulta de carga (A9)
#   Etapa 9  · emitir comandos remotos, reconocer alarmas
#   Etapa 10 · solicitar cita y consultar ubicación «solo los propios» de
#              TRANSPORTISTA, vía el bot (§7.5.6: mismo control de propiedad)
ACCION_VER_MANIFIESTOS = Accion(
    nombre="ver_manifiestos",
    roles_permitidos=frozenset({Rol.TERMINAL, Rol.NAVIERA, Rol.AGENTE, Rol.AUTORIDAD}),
    frase_rechazo="ver manifiestos completos",
)
ACCION_GENERAR_CODIGO_VINCULACION = Accion(
    nombre="generar_codigo_vinculacion",
    roles_permitidos=frozenset({Rol.TERMINAL}),
    frase_rechazo="generar códigos de vinculación de transportistas",
)
ACCION_VER_TURNOS = Accion(
    nombre="ver_turnos",
    roles_permitidos=frozenset({Rol.TERMINAL}),
    frase_rechazo="ver los turnos de la terminal",
)
ACCION_GESTIONAR_TURNOS = Accion(
    nombre="gestionar_turnos",
    roles_permitidos=frozenset({Rol.TERMINAL}),
    frase_rechazo="retener o anular turnos",
)
ACCION_VER_RETENCIONES = Accion(
    nombre="ver_retenciones",
    roles_permitidos=frozenset({Rol.TERMINAL, Rol.AUTORIDAD}),
    frase_rechazo="ver la bandeja de retenciones",
)
ACCION_RESOLVER_RETENCION = Accion(
    nombre="resolver_retencion",
    roles_permitidos=frozenset({Rol.TERMINAL, Rol.AUTORIDAD}),
    frase_rechazo="resolver retenciones",
)

# Etapa 6 · TERMINAL (§14, §6.3, §12.2, §12.6, §13.3, §11.4, §15.1, §16.3).
ACCION_VER_SINOPTICO = Accion(
    nombre="ver_sinoptico",
    roles_permitidos=frozenset({Rol.TERMINAL}),
    frase_rechazo="ver el sinóptico de operación",
)
ACCION_EMITIR_COMANDO = Accion(
    nombre="emitir_comando",
    roles_permitidos=frozenset({Rol.TERMINAL}),
    frase_rechazo="emitir comandos remotos al controlador",
)
ACCION_GESTIONAR_PATIO = Accion(
    nombre="gestionar_patio",
    roles_permitidos=frozenset({Rol.TERMINAL}),
    frase_rechazo="bloquear o liberar posiciones del patio",
)
ACCION_VER_GRUA = Accion(
    nombre="ver_grua",
    roles_permitidos=frozenset({Rol.TERMINAL}),
    frase_rechazo="ver la pestaña de grúa",
)
ACCION_EXPORTAR_GRUA = Accion(
    nombre="exportar_grua",
    roles_permitidos=frozenset({Rol.TERMINAL}),
    frase_rechazo="exportar el historial de grúa",
)
ACCION_RECONOCER_ALARMA = Accion(
    nombre="reconocer_alarma",
    roles_permitidos=frozenset({Rol.TERMINAL}),
    frase_rechazo="reconocer alarmas",
)
ACCION_GESTIONAR_CITAS = Accion(
    nombre="gestionar_citas",
    roles_permitidos=frozenset({Rol.TERMINAL}),
    frase_rechazo="cancelar, reprogramar o bloquear citas",
)
ACCION_GENERAR_REPORTE = Accion(
    nombre="generar_reporte",
    roles_permitidos=frozenset({Rol.TERMINAL}),
    frase_rechazo="generar reportes de corrida",
)

# Etapa 7 · Cadena documental: NAVIERA, AGENTE, AUTORIDAD (§9, §14.7-§14.9).
ACCION_CREAR_MANIFIESTO = Accion(
    nombre="crear_manifiesto",
    roles_permitidos=frozenset({Rol.NAVIERA}),
    frase_rechazo="crear manifiestos",
)
ACCION_ANULAR_MANIFIESTO = Accion(
    nombre="anular_manifiesto",
    roles_permitidos=frozenset({Rol.NAVIERA}),
    frase_rechazo="anular manifiestos",
)
ACCION_VER_CONTENEDORES_PROPIOS = Accion(
    nombre="ver_contenedores_propios",
    roles_permitidos=frozenset({Rol.NAVIERA}),
    frase_rechazo="ver sus contenedores",
)
ACCION_PRESENTAR_DECLARACION = Accion(
    nombre="presentar_declaracion",
    roles_permitidos=frozenset({Rol.AGENTE}),
    frase_rechazo="presentar declaraciones de mercancías",
)
ACCION_SOLICITAR_LEVANTE = Accion(
    nombre="solicitar_levante",
    roles_permitidos=frozenset({Rol.AGENTE}),
    frase_rechazo="solicitar levantes",
)
ACCION_VER_SEGUIMIENTO = Accion(
    nombre="ver_seguimiento",
    roles_permitidos=frozenset({Rol.AGENTE}),
    frase_rechazo="ver el seguimiento de sus solicitudes",
)
ACCION_OTORGAR_LEVANTE = Accion(
    nombre="otorgar_levante",
    roles_permitidos=frozenset({Rol.AUTORIDAD}),
    frase_rechazo="otorgar o retener levantes",
)
ACCION_CONSULTAR_CARGA = Accion(
    nombre="consultar_carga",
    roles_permitidos=frozenset({Rol.AUTORIDAD}),
    frase_rechazo="consultar la carga de cualquier contenedor",
)

# Etapa 8 · Retenciones y parqueo (§10.2, A9): RT05 la ordena solo la autoridad.
ACCION_ORDENAR_RETENCION_DOCUMENTAL = Accion(
    nombre="ordenar_retencion_documental",
    roles_permitidos=frozenset({Rol.AUTORIDAD}),
    frase_rechazo="ordenar retenciones documentales (RT05)",
)

CLAVE_CONTEXTO = "contexto_portus"


def respuesta_error(codigo_http: int, error: str, mensaje: str) -> Respuesta:
    """Cuerpo de error uniforme para toda la API (§7.5.1; S-5 sin detalles internos)."""
    respuesta = flask.jsonify({"error": error, "mensaje": mensaje})
    respuesta.status_code = codigo_http
    return respuesta


def _auditar_rechazo(accion: str, usuario: Usuario, recurso: str, motivo: str) -> None:
    """Deja constancia del intento rechazado (§7.5.5); nunca tumba la petición."""
    repositorio = cast(
        RepositorioAuditoria | None, flask.current_app.extensions.get(CLAVE_AUDITORIA)
    )
    if repositorio is None:  # solo en pruebas unitarias mínimas sin aplicación completa
        REGISTRO.warning("Sin repositorio de auditoría: rechazo no registrado (%s)", accion)
        return
    repositorio.registrar(
        accion=accion,
        recurso=recurso,
        motivo=motivo,
        instante=marca_utc(),
        username=usuario.username,
        rol=usuario.rol.value,
    )


def requiere_sesion_json(ver: Vista) -> Vista:
    """Exige sesión; sin ella responde ``401`` en JSON (§18: toda ruta salvo /login)."""

    @functools.wraps(ver)
    def envuelto(*args: object, **kwargs: object) -> Respuesta:
        usuario = usuario_en_sesion(flask.session)
        if usuario is None:
            return respuesta_error(401, ERROR_SIN_SESION, MENSAJE_SIN_SESION)
        return ver(*args, **kwargs)

    return envuelto


def requiere_rol(accion: Accion) -> Callable[[Vista], Vista]:
    """Aplica la fila de la matriz §7.4 correspondiente en el servidor (§7.5.1).

    El endpoint decorado recibe el control solo si hay sesión y el rol del
    usuario está entre los permitidos de la acción; en caso contrario el
    servidor responde ``403`` con el mensaje explícito de la acción y
    registra el rechazo en la auditoría (§7.5.5).
    """

    def envolver(ver: Vista) -> Vista:
        @functools.wraps(ver)
        def envuelto(*args: object, **kwargs: object) -> Respuesta:
            usuario = usuario_en_sesion(flask.session)
            if usuario is None:
                return respuesta_error(401, ERROR_SIN_SESION, MENSAJE_SIN_SESION)
            if usuario.rol not in accion.roles_permitidos:
                _auditar_rechazo(
                    accion.nombre,
                    usuario,
                    recurso=flask.request.path,
                    motivo="rol_no_permitido",
                )
                REGISTRO.warning(
                    "Rechazo §7.5: %s (rol %s) intentó %s en %s",
                    usuario.username,
                    usuario.rol.value,
                    accion.nombre,
                    flask.request.path,
                )
                return respuesta_error(
                    403,
                    ERROR_ACCION_NO_PERMITIDA,
                    f"El rol {usuario.rol.value} no puede {accion.frase_rechazo}.",
                )
            return ver(*args, **kwargs)

        return envuelto

    return envolver


def requiere_sesion_html(ver: Vista) -> Vista:
    """Para las páginas: sin sesión redirige al formulario de login (§7.3)."""

    @functools.wraps(ver)
    def envuelto(*args: object, **kwargs: object) -> Respuesta:
        if usuario_en_sesion(flask.session) is None:
            return flask.redirect("/login")
        return ver(*args, **kwargs)

    return envuelto
