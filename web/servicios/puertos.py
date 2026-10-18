"""Puerto de salida MQTT de la lógica del servidor (CODESTYLE A-2, PY-7).

Los servicios no conocen paho ni Flask: publican a través de este contrato,
que el núcleo implementa con el cliente MQTT de ``web/mqtt``. En pruebas se
inyecta un duplicado que captura las publicaciones (T-5).
"""

from typing import Protocol


class PublicadorLogica(Protocol):
    """Contrato de publicación del carril Aplicación hacia el broker."""

    def publicar(self, topico: str, tipo: str, datos: dict[str, object]) -> None:
        """Publica el envoltorio §5.2 completo en el tópico indicado (QoS 1)."""
        ...

    def publicar_comando(self, nombre: str, parametros: dict[str, str], usuario: str) -> str:
        """Envía una solicitud de comando (§6.4) y devuelve su ``cmd_id``."""
        ...
