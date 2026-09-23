"""Comandos remotos desde la pestaña Operación (SPECS §6.1-§6.4, Etapa 6).

El TERMINAL emite los 13 comandos del catálogo §6.1 desde la web; el flujo
completo (solicitud → CMD → RSP → respuesta publicada) lo orquesta el puente
(§6.4). Aquí solo se construye y publica la solicitud en
``portus/cmd/solicitud`` y se devuelve el ``cmd_id`` para que la interfaz
correlacione la respuesta ACK/NAK que llega por MQTT sobre WebSocket (§6.2
regla 1: el usuario siempre ve la respuesta).
"""

import logging

from web.servicios.puertos import PublicadorLogica

REGISTRO = logging.getLogger(__name__)

# Comandos que exigen confirmación explícita del operador antes de emitirse
# (SPECS §6.3 columna «Confirmación: Sí»). El resto no la requiere.
COMANDOS_CON_CONFIRMACION = frozenset({"AbrirTalanquera", "AbrirPuertaSalida", "ModoMantenimiento"})


class ServicioComandos:
    """Emite solicitudes de comando remoto hacia el puente (§6.3, §6.4)."""

    def __init__(self, publicador: PublicadorLogica) -> None:
        self._publicador = publicador

    def emitir(self, nombre: str, parametros: dict[str, str], usuario: str) -> str:
        """Publica la solicitud y devuelve el ``cmd_id`` (§6.4).

        La confirmación de UI (si el comando la exige) la pide la interfaz
        antes de llamar aquí; el servidor no asume nada sobre el clic.
        """
        cmd_id = self._publicador.publicar_comando(nombre, parametros, usuario)
        REGISTRO.info("Comando %s emitido por %s (cmd_id=%s)", nombre, usuario, cmd_id)
        return cmd_id
