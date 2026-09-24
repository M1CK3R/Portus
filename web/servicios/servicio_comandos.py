"""Comandos remotos desde la pestaña Operación (SPECS §6.1-§6.4, Etapa 6).

El TERMINAL emite los 13 comandos del catálogo §6.1 desde la web; el flujo
completo (solicitud → CMD → RSP → respuesta publicada) lo orquesta el puente
(§6.4). Aquí solo se construye y publica la solicitud en
``portus/cmd/solicitud`` y se devuelve el ``cmd_id`` para que la interfaz
correlacione la respuesta ACK/NAK que llega por MQTT sobre WebSocket (§6.2
regla 1: el usuario siempre ve la respuesta).

La disponibilidad de §6.3 también se aplica aquí, no solo deshabilitando el
botón: Reanudar exige grúa suspendida y Referenciar grúa en reposo o
suspendida, según el último latido. Sin latido aún, decide el controlador.
Las condiciones de rechazo de §6.1 las evalúa siempre el controlador (§6.4).
"""

import logging
import threading

from puente.protocolo import (
    CMD_AGUJA_LIBERAR,
    CMD_GRUA_REANUDAR,
    CMD_GRUA_REFERENCIAR,
    CMD_MODO_MANTENIMIENTO,
    CMD_POSICION_BLOQUEAR,
    CMD_POSICION_LIBERAR,
    NOMBRES_COMANDOS,
)
from web.modelos.comando import ESTADOS_GRUA_REFERENCIABLE, GRUA_SUSPENDIDA, EstadoControlador
from web.servicios.puertos import PublicadorLogica

REGISTRO = logging.getLogger(__name__)

# Comandos que exigen confirmación explícita del operador antes de emitirse
# (SPECS §6.3 columna «Confirmación: Sí»). El resto no la requiere.
COMANDOS_CON_CONFIRMACION = frozenset({"AbrirTalanquera", "AbrirPuertaSalida", "ModoMantenimiento"})

# Comandos cuyo efecto en la BD depende del ACK: tienen endpoint propio que
# valida la precondición de §6.3 y registra la espera de la respuesta.
COMANDOS_CON_RUTA_PROPIA = {
    CMD_POSICION_BLOQUEAR: "/api/patio/posiciones/<id>/bloquear",
    CMD_POSICION_LIBERAR: "/api/patio/posiciones/<id>/liberar",
    CMD_AGUJA_LIBERAR: "/api/parqueo/<plaza>/liberar",
}
VALORES_MODO_MANTENIMIENTO = frozenset({"ACTIVAR", "DESACTIVAR"})


class ErrorComando(Exception):
    """Solicitud de comando inválida antes de llegar al controlador (§6.1, D-10)."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


class ServicioComandos:
    """Emite solicitudes de comando remoto hacia el puente (§6.3, §6.4)."""

    def __init__(self, publicador: PublicadorLogica) -> None:
        self._publicador = publicador
        self._estado: EstadoControlador | None = None
        self._candado = threading.Lock()

    def actualizar_estado(self, modo: str, grua: str, ts: str) -> None:
        """Guarda modo y grúa del último latido ``EST`` (§5.4); lo llama el núcleo."""
        with self._candado:
            self._estado = EstadoControlador(modo=modo.upper(), grua=grua.upper(), ts=ts)

    @property
    def estado_controlador(self) -> EstadoControlador | None:
        with self._candado:
            return self._estado

    def _exigir_disponibilidad(self, nombre: str) -> None:
        """§6.3: Reanudar solo suspendida; Referenciar solo en reposo o suspendida."""
        estado = self.estado_controlador
        if estado is None:
            return
        if nombre == CMD_GRUA_REANUDAR and estado.grua != GRUA_SUSPENDIDA:
            raise ErrorComando(
                "COMANDO_NO_DISPONIBLE",
                f"GruaReanudar solo con la grúa suspendida (estado: {estado.grua})",
            )
        if nombre == CMD_GRUA_REFERENCIAR and estado.grua not in ESTADOS_GRUA_REFERENCIABLE:
            raise ErrorComando(
                "COMANDO_NO_DISPONIBLE",
                f"GruaReferenciar solo con la grúa en reposo o suspendida (estado: {estado.grua})",
            )

    def emitir(self, nombre: str, parametros: dict[str, str], usuario: str) -> str:
        """Valida y publica la solicitud; devuelve el ``cmd_id`` (§6.4).

        La confirmación de UI (si el comando la exige) la pide la interfaz
        antes de llamar aquí; el servidor no asume nada sobre el clic.
        Lanza :class:`ErrorComando` si el nombre no es del catálogo §6.1, si
        el comando tiene endpoint propio o si faltan sus parámetros.
        """
        if nombre not in NOMBRES_COMANDOS:
            raise ErrorComando("COMANDO_DESCONOCIDO", f"'{nombre}' no está en el catálogo §6.1")
        if nombre in COMANDOS_CON_RUTA_PROPIA:
            raise ErrorComando(
                "COMANDO_CON_RUTA_PROPIA",
                f"{nombre} se emite con {COMANDOS_CON_RUTA_PROPIA[nombre]}",
            )
        if (
            nombre == CMD_MODO_MANTENIMIENTO
            and parametros.get("valor") not in VALORES_MODO_MANTENIMIENTO
        ):
            raise ErrorComando(
                "PARAMETRO_INVALIDO",
                f"ModoMantenimiento exige valor ACTIVAR o DESACTIVAR "
                f"(recibido: {parametros.get('valor')!r})",
            )
        self._exigir_disponibilidad(nombre)
        cmd_id = self._publicador.publicar_comando(nombre, parametros, usuario)
        REGISTRO.info("Comando %s emitido por %s (cmd_id=%s)", nombre, usuario, cmd_id)
        return cmd_id
