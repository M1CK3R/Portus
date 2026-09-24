"""Alarmas en la plataforma (SPECS §13, §6.2, Etapa 9).

* Ingreso: las del controlador (``ALM`` → ``alarma.controlador``), AL01 del
  puente (``alarma.servidor`` con código AL01) y AL14 al recibir un NAK. Las
  demás del servidor (AL09-AL13) las emiten sus servicios con el mismo
  :class:`EmisorAlarmas`. Todas llevan severidad y origen del catálogo §13.1.
* Ciclo de vida: una alarma no desaparece sola; solo TERMINAL la reconoce
  (la ruta lo exige), CRITICA y ALTA una por una, BAJA y MEDIA también en
  lote (§13.3). AL01 queda activa aunque el enlace vuelva (§13.4).
* ``AlarmaSilenciar`` (comando 13) acalla la sirena **sin** reconocer (§13.4).
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.alarma import (
    DEFINICIONES,
    ORIGEN_CONTROLADOR,
    Alarma,
    CodigoAlarma,
    definicion,
)
from web.modelos.comando import texto_causa
from web.repositorios.repositorio_alarmas import RepositorioAlarmas
from web.servicios.emisor_alarmas import EmisorAlarmas
from web.servicios.puertos import PublicadorLogica
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)

CMD_ALARMA_SILENCIAR = "AlarmaSilenciar"
CLAVES_CONTROLADOR_OMITIDAS = frozenset({"codigo", "severidad", "descripcion"})
"""El catálogo manda sobre lo que diga la trama (N-7); el resto se conserva."""


class ErrorAlarma(Exception):
    """Reconocimiento no aplicable: inexistente o ya reconocida (§13.2)."""


class ServicioAlarmas:
    """Alta de alarmas externas, reconocimiento y listado (§13.2, §13.3)."""

    def __init__(
        self,
        alarmas: RepositorioAlarmas,
        emisor: EmisorAlarmas,
        publicador: PublicadorLogica,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._alarmas = alarmas
        self._emisor = emisor
        self._publicador = publicador
        self._fabrica_instante = fabrica_instante

    # ----------------------------------------------------------------- ingreso

    def procesar_alarma_controlador(self, datos: dict[str, object], ts: str) -> int | None:
        """ALM del controlador (AL02-AL08): se persiste con la severidad del catálogo.

        Un código fuera de AL01-AL14 se registra y se descarta (P-5); si la
        severidad de la trama difiere del catálogo, gana el catálogo y se avisa.
        """
        codigo = str(datos.get("codigo", ""))
        entrada = definicion(codigo)
        if entrada is None:
            REGISTRO.warning("ALM con código desconocido '%s'; se descarta (P-5)", codigo)
            return None
        if entrada.origen != ORIGEN_CONTROLADOR:
            REGISTRO.warning("ALM %s: el catálogo la asigna al servidor; se registra igual", codigo)
        severidad = datos.get("severidad")
        if severidad not in (None, entrada.severidad.value):
            REGISTRO.warning(
                "ALM %s llegó con severidad %s; el catálogo §13.1 dice %s",
                codigo,
                severidad,
                entrada.severidad.value,
            )
        extra = {k: v for k, v in datos.items() if k not in CLAVES_CONTROLADOR_OMITIDAS}
        return self._emisor.emitir(entrada.codigo, extra, ts, anunciar=False)

    def procesar_alarma_enlace(self, datos: dict[str, object], ts: str) -> int | None:
        """AL01 publicada por el vigilante del puente (§5.4, A14): se persiste aquí.

        Solo AL01 llega por este camino; las demás ``alarma.servidor`` las
        emitió esta misma web y ya están en la tabla.
        """
        if datos.get("codigo") != CodigoAlarma.AL01.value:
            return None
        extra = {k: v for k, v in datos.items() if k not in CLAVES_CONTROLADOR_OMITIDAS}
        return self._emisor.emitir(CodigoAlarma.AL01, extra, ts, anunciar=False)

    def procesar_comando_rechazado(self, datos: dict[str, object]) -> int:
        """AL14 por todo NAK, también el sintético SIN_RESPUESTA (§6.2 regla 2, §4.5)."""
        causa = datos.get("causa")
        causa_texto = str(causa) if isinstance(causa, str) else None
        contenido: dict[str, object] = {
            "cmd_id": datos.get("cmd_id"),
            "nombre": datos.get("nombre"),
            "causa": causa_texto,
            "texto_causa": texto_causa(causa_texto),
            "sintetica": bool(datos.get("sintetica", False)),
        }
        return self._emisor.emitir(CodigoAlarma.AL14, contenido)

    # ---------------------------------------------------------------- lectura

    def activas(self, severidad: str | None = None) -> list[Alarma]:
        """Lista de alarmas activas; ``severidad`` filtra (§13.3)."""
        return self._alarmas.activas(severidad=severidad)

    def historicas(self, severidad: str | None = None) -> list[Alarma]:
        return self._alarmas.historicas(severidad=severidad)

    def cantidad_activas(self) -> int:
        return self._alarmas.cantidad_activas()

    # ---------------------------------------------------------- reconocimiento

    def reconocer(
        self, alarma_id: int, usuario_id: int, usuario: str, comentario: str | None = None
    ) -> Alarma:
        """Pasa una alarma activa a reconocida (§13.2); lanza :class:`ErrorAlarma` si no aplica."""
        alarma = self._alarmas.buscar_por_id(alarma_id)
        if alarma is None:
            raise ErrorAlarma(f"no existe la alarma {alarma_id}")
        ts = marca_utc(self._fabrica_instante())
        if not self._alarmas.reconocer(alarma_id, usuario_id, comentario, ts):
            raise ErrorAlarma(f"la alarma {alarma_id} ({alarma.codigo}) ya estaba reconocida")
        self._emisor.anunciar_reconocida(alarma_id, alarma.codigo, usuario)
        REGISTRO.info("Alarma %d (%s) reconocida por %s", alarma_id, alarma.codigo, usuario)
        return self._alarmas.buscar_por_id(alarma_id) or alarma

    def reconocer_todas_baja_media(self, usuario_id: int, usuario: str) -> int:
        """Reconoce en lote las de severidad BAJA y MEDIA (§13.3).

        Las CRITICA y ALTA se reconocen una por una; esta operación las excluye.
        """
        ts = marca_utc(self._fabrica_instante())
        cantidad = self._alarmas.reconocer_todas_baja_media(usuario_id, ts)
        if cantidad:
            self._emisor.anunciar_reconocida(0, "LOTE", usuario)
        REGISTRO.info("Reconocidas %d alarmas (baja/media) en lote por %s", cantidad, usuario)
        return cantidad

    def silenciar(self, usuario: str) -> str:
        """Silencia la señal sonora sin reconocer la alarma (§13.4, comando 13).

        ``AlarmaSilenciar`` nunca se rechaza (§6.1); el controlador acalla la
        sirena pero las alarmas siguen activas hasta su reconocimiento.
        """
        cmd_id = self._publicador.publicar_comando(CMD_ALARMA_SILENCIAR, {}, usuario)
        REGISTRO.info("AlarmaSilenciar enviado por %s (cmd_id=%s)", usuario, cmd_id)
        return cmd_id


def catalogo() -> list[dict[str, str]]:
    """Catálogo §13.1 para la pestaña Alarmas (código, severidad, origen, descripción)."""
    return [
        {
            "codigo": d.codigo.value,
            "severidad": d.severidad.value,
            "origen": d.origen,
            "descripcion": d.descripcion,
        }
        for d in DEFINICIONES.values()
    ]
