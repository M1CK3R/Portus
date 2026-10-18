"""Punto único de alta de alarmas (SPECS §13.1, §13.2, §13.4).

Toda alarma, la genere el servidor, el controlador (``ALM``) o el puente
(AL01), entra por aquí: la severidad, la descripción y el origen salen del
catálogo (CODESTYLE N-7), la fila se persiste con la deduplicación de §13.4
y se publica en ``portus/srv/alarma`` el recuento de activas para que el
sinóptico muestre el número exacto sin consultar la base (JS-2).
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.alarma import DEFINICIONES, CodigoAlarma
from web.repositorios.repositorio_alarmas import RepositorioAlarmas
from web.servicios.puertos import PublicadorLogica
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

TOPICO_SRV_ALARMA = "portus/srv/alarma"
TIPO_ALARMA_SERVIDOR = "alarma.servidor"
TIPO_ALARMA_RESUMEN = "alarma.resumen"
TIPO_ALARMA_RECONOCIDA = "alarma.reconocida"


class EmisorAlarmas:
    """Persiste y anuncia alarmas con los datos del catálogo §13.1."""

    def __init__(
        self,
        alarmas: RepositorioAlarmas,
        publicador: PublicadorLogica,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._alarmas = alarmas
        self._publicador = publicador
        self._fabrica_instante = fabrica_instante

    def emitir(
        self,
        codigo: CodigoAlarma,
        datos: dict[str, object],
        ts: str | None = None,
        anunciar: bool = True,
    ) -> int:
        """Registra la alarma (o suma una repetición) y devuelve su id.

        ``anunciar=False`` cuando el evento ya circuló por MQTT desde su
        origen (ALM del controlador, AL01 del puente): solo se publica el
        recuento, así el sinóptico no cuenta dos veces la misma alarma.
        """
        definicion = DEFINICIONES[codigo]
        marca = ts or marca_utc(self._fabrica_instante())
        alarma_id = self._alarmas.registrar(
            codigo.value,
            definicion.severidad.value,
            definicion.origen,
            definicion.descripcion,
            datos,
            marca,
        )
        if anunciar:
            self._publicador.publicar(
                TOPICO_SRV_ALARMA,
                TIPO_ALARMA_SERVIDOR,
                {
                    "codigo": codigo.value,
                    "severidad": definicion.severidad.value,
                    "descripcion": definicion.descripcion,
                    "alarma": alarma_id,
                    **datos,
                },
            )
        self.anunciar_recuento()
        REGISTRO.warning(
            "%s (%s) registrada: %s",
            codigo.value,
            definicion.severidad.value,
            definicion.descripcion,
        )
        return alarma_id

    def anunciar_recuento(self) -> None:
        """Publica cuántas alarmas siguen activas (§13.2: no desaparecen solas)."""
        self._publicador.publicar(
            TOPICO_SRV_ALARMA,
            TIPO_ALARMA_RESUMEN,
            {"activas": self._alarmas.cantidad_activas()},
        )

    def anunciar_reconocida(self, alarma_id: int, codigo: str, usuario: str) -> None:
        """Avisa el reconocimiento para refrescar la pestaña Alarmas y el sinóptico."""
        self._publicador.publicar(
            TOPICO_SRV_ALARMA,
            TIPO_ALARMA_RECONOCIDA,
            {"alarma": alarma_id, "codigo": codigo, "usuario": usuario},
        )
        self.anunciar_recuento()
