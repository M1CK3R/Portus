"""Atención de los comandos del transportista (SPECS §15.1, §15.2).

Recibe mensajes y pulsaciones ya traducidos a modelos propios y devuelve una
:class:`Respuesta`; nunca devuelve «nada»: texto sin comando o comando
desconocido reciben «comando no reconocido» con ``/ayuda`` (§15.2 reglas).

Reglas de acceso:

* Cuenta **no vinculada**: todo lo que no sea ``/vincular`` (incluidos
  ``/start`` e ``/inicio``) recibe siempre la misma respuesta (§15.1 regla 5).
  ``/start CODIGO`` es el enlace ``t.me/<bot>?start=CODIGO`` y vincula (§15.4).
* Cuenta vinculada: el ``transportista_id`` sale **del vínculo del chat**,
  nunca de lo que escribe el usuario, y cada consulta lo aplica en el SQL
  (S-2, PY-3).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from mensajeria.conversaciones import LimitadorVinculacion, RegistroConversaciones
from mensajeria.flujo_cita import FlujoCita
from mensajeria.formato import lista_con_tope, marca_legible, permanencia_desde
from mensajeria.modelos import MensajeEntrante, PulsacionBoton, Respuesta
from mensajeria.redactor import ventana_legible
from mensajeria.textos import (
    CANAL_TEXTO,
    COMANDO_START,
    ESTACION_POR_ESTADO,
    ESTADO_CITA_TEXTO,
    ESTADO_DOCUMENTAL_TEXTO,
    ESTADO_OPERATIVO_TEXTO,
    TEXTO_CODIGO_INVALIDO,
    TEXTO_DEMASIADOS_INTENTOS,
    TEXTO_ESTADO_USO,
    TEXTO_NO_RECONOCIDO,
    TEXTO_SIN_CARGA,
    TEXTO_SIN_CITAS,
    TEXTO_SIN_TURNOS,
    TEXTO_VINCULAR_USO,
    TIPO_OP_TEXTO,
    lista_de_comandos,
    texto_ayuda,
    texto_inicio,
    texto_sin_vincular,
)
from web.modelos.cita import ZONA_LOCAL
from web.modelos.turno import EstadoTurno
from web.modelos.usuario import Rol, Usuario
from web.repositorios.repositorio_citas import RepositorioCitas
from web.repositorios.repositorio_consultas_transportista import (
    EstadoContenedor,
    RepositorioConsultasTransportista,
    TurnoActivo,
)
from web.repositorios.repositorio_usuarios import RepositorioUsuarios
from web.repositorios.repositorio_vinculos import RepositorioVinculos
from web.servicios.servicio_vinculacion import ServicioVinculacion

PREFIJO_COMANDO = "/"
SEPARADOR_MENCION = "@"
"""En grupos Telegram escribe ``/estado@PortusBot``; la mención se descarta."""
PATRON_CONTENEDOR = re.compile(r"^[A-Za-z0-9-]{1,20}$")
"""Identificador aceptado en /estado; otro texto ni siquiera llega al SQL (S-2)."""

Manejador = Callable[[int, Usuario, str], Respuesta]


@dataclass(frozen=True)
class DependenciasBot:
    """Todo lo que el bot usa, inyectado una sola vez (PY-7)."""

    vinculacion: ServicioVinculacion
    vinculos: RepositorioVinculos
    usuarios: RepositorioUsuarios
    citas: RepositorioCitas
    consultas: RepositorioConsultasTransportista
    flujo_cita: FlujoCita
    conversaciones: RegistroConversaciones
    limitador: LimitadorVinculacion
    nombre_terminal: str
    fabrica_instante: Callable[[], datetime]


def interpretar(texto: str) -> tuple[str | None, str]:
    """(comando en minúsculas sin «/» ni mención, argumento); comando None si es texto."""
    limpio = texto.strip()
    if not limpio.startswith(PREFIJO_COMANDO):
        return (None, limpio)
    primera, _, resto = limpio.partition(" ")
    comando = primera[len(PREFIJO_COMANDO) :].split(SEPARADOR_MENCION, 1)[0].lower()
    return (comando, resto.strip())


class ServicioBot:
    """Los 7 comandos de §15.2 y los botones de ``/cita``."""

    def __init__(self, dependencias: DependenciasBot) -> None:
        self._d = dependencias
        self._comandos: dict[str, Manejador] = {
            "inicio": self._inicio,
            COMANDO_START: self._inicio,
            "cita": self._cita,
            "miscitas": self._mis_citas,
            "estado": self._estado,
            "misturnos": self._mis_turnos,
            "ayuda": self._ayuda,
        }

    def atender_mensaje(self, mensaje: MensajeEntrante) -> Respuesta:
        """Responde siempre: vínculo, comando conocido o «no reconocido»."""
        comando, argumento = interpretar(mensaje.texto)
        if comando == "vincular" or (comando == COMANDO_START and argumento):
            return self._vincular(mensaje.id_chat, argumento)
        usuario = self._usuario_del_chat(mensaje.id_chat)
        if usuario is None:
            return Respuesta(texto_sin_vincular(self._d.nombre_terminal))
        # §15.2 [PROP]: cualquier otro mensaje cancela la conversación de /cita.
        self._d.conversaciones.cancelar(mensaje.id_chat)
        manejador = self._comandos.get(comando) if comando is not None else None
        if manejador is None:
            return Respuesta(TEXTO_NO_RECONOCIDO)
        return manejador(mensaje.id_chat, usuario, argumento)

    def atender_pulsacion(self, pulsacion: PulsacionBoton) -> Respuesta:
        """Botones de ``/cita``; una cuenta no vinculada recibe la respuesta única."""
        usuario = self._usuario_del_chat(pulsacion.id_chat)
        if usuario is None:
            return Respuesta(texto_sin_vincular(self._d.nombre_terminal))
        return self._d.flujo_cita.atender(pulsacion, usuario.id)

    # ------------------------------------------------------------ vinculación

    def _vincular(self, id_chat: int, codigo: str) -> Respuesta:
        """``/vincular CODIGO`` (§15.1 pasos 2-4) con tope de intentos por chat."""
        if not codigo:
            return Respuesta(TEXTO_VINCULAR_USO)
        if not self._d.limitador.permitir(id_chat):
            return Respuesta(TEXTO_DEMASIADOS_INTENTOS)
        usuario = self._d.vinculacion.vincular_cuenta(codigo, id_chat)
        if usuario is None:
            return Respuesta(TEXTO_CODIGO_INVALIDO)
        self._d.conversaciones.cancelar(id_chat)
        return Respuesta(
            f"✅ Cuenta vinculada: {usuario.nombre_mostrado}.\n"
            f"Desde ahora recibirás aquí los avisos de {self._d.nombre_terminal}.\n\n"
            f"Comandos disponibles:\n{lista_de_comandos()}"
        )

    def _usuario_del_chat(self, id_chat: int) -> Usuario | None:
        """Transportista activo ligado al chat; None si no hay vínculo válido."""
        transportista_id = self._d.vinculos.transportista_de_chat(id_chat)
        if transportista_id is None:
            return None
        usuario = self._d.usuarios.buscar_por_id(transportista_id)
        if usuario is None or not usuario.activo or usuario.rol is not Rol.TRANSPORTISTA:
            return None
        return usuario

    # --------------------------------------------------------------- comandos

    def _inicio(self, id_chat: int, usuario: Usuario, _argumento: str) -> Respuesta:
        return Respuesta(texto_inicio(self._d.nombre_terminal, usuario.nombre_mostrado))

    def _ayuda(self, id_chat: int, usuario: Usuario, _argumento: str) -> Respuesta:
        return Respuesta(texto_ayuda())

    def _cita(self, id_chat: int, usuario: Usuario, _argumento: str) -> Respuesta:
        return self._d.flujo_cita.iniciar(id_chat, usuario.id)

    def _mis_citas(self, id_chat: int, usuario: Usuario, _argumento: str) -> Respuesta:
        """Citas de hoy en adelante más las programadas atrasadas (§15.2)."""
        hoy = self._d.fabrica_instante().astimezone(ZONA_LOCAL).strftime("%Y-%m-%d")
        citas = self._d.citas.del_transportista(usuario.id, hoy)
        if not citas:
            return Respuesta(TEXTO_SIN_CITAS)
        bloques = [
            f"Contenedor {c.contenedor_id}\nFranja: {ventana_legible(c.fecha, c.inicio, c.fin)}"
            f"\nEstado: {ESTADO_CITA_TEXTO.get(c.estado, c.estado)}"
            for c in citas
        ]
        return Respuesta(lista_con_tope("Tus citas:", bloques))

    def _estado(self, id_chat: int, usuario: Usuario, argumento: str) -> Respuesta:
        """``/estado CONTENEDOR``: solo carga propia; lo ajeno parece inexistente (§15.2)."""
        if not argumento:
            return Respuesta(TEXTO_ESTADO_USO)
        identificador = argumento.split()[0]
        if not PATRON_CONTENEDOR.match(identificador):
            return Respuesta(TEXTO_SIN_CARGA)
        estado = self._d.consultas.estado_contenedor(usuario.id, identificador)
        if estado is None:
            return Respuesta(TEXTO_SIN_CARGA)
        return Respuesta(self._texto_estado(estado))

    def _mis_turnos(self, id_chat: int, usuario: Usuario, _argumento: str) -> Respuesta:
        """Turnos activos con vehículo, contenedor, tipo, estado y estación (§15.2)."""
        turnos = self._d.consultas.turnos_activos(usuario.id)
        if not turnos:
            return Respuesta(TEXTO_SIN_TURNOS)
        return Respuesta(
            lista_con_tope("Tus operaciones en curso:", [_texto_turno(t) for t in turnos])
        )

    def _texto_estado(self, estado: EstadoContenedor) -> str:
        lineas = [
            f"Contenedor {estado.contenedor_id} · "
            f"{TIPO_OP_TEXTO.get(estado.tipo_op, estado.tipo_op)}",
            f"Estado actual: {_estado_actual(estado)}",
        ]
        if estado.posicion is not None:
            lineas.append(f"Ubicación: posición {estado.posicion}, nivel {estado.nivel}")
        if estado.ingreso_en is not None:
            permanencia = permanencia_desde(estado.ingreso_en, self._d.fabrica_instante())
            lineas.append(
                f"Permanencia en patio: {permanencia} (desde {marca_legible(estado.ingreso_en)})"
            )
        documental = ESTADO_DOCUMENTAL_TEXTO.get(estado.estado_documental, estado.estado_documental)
        canal = CANAL_TEXTO.get(estado.canal, estado.canal) if estado.canal else "sin asignar"
        lineas.append(f"Autorización: {documental}")
        lineas.append(f"Canal: {canal}")
        return "\n".join(lineas)


def _estado_actual(estado: EstadoContenedor) -> str:
    """Turno en curso con su estación, patio o el estado operativo del manifiesto."""
    if estado.estado_turno is not None:
        estacion = ESTACION_POR_ESTADO.get(estado.estado_turno, estado.estado_turno)
        return f"en operación ({estado.estado_turno} · {estacion})"
    if estado.posicion is not None:
        return "en el patio de la terminal"
    return ESTADO_OPERATIVO_TEXTO.get(estado.estado_operativo, estado.estado_operativo)


def _texto_turno(turno: TurnoActivo) -> str:
    estacion = ESTACION_POR_ESTADO.get(turno.estado, turno.estado)
    if turno.estado == EstadoTurno.RETENIDO.value and turno.plaza is not None:
        estacion = f"{estacion}, plaza {turno.plaza}"
    return (
        f"Turno {turno.id} · {TIPO_OP_TEXTO.get(turno.tipo_op, turno.tipo_op)}\n"
        f"Vehículo: {turno.vehiculo}\nContenedor: {turno.contenedor_id}\n"
        f"Estado: {turno.estado}\nEstación: {estacion}"
    )
