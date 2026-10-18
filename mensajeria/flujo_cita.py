"""Conversación de ``/cita``: contenedor → franja → confirmación (SPECS §15.2, §11.3).

1. Lista los contenedores del transportista **con levante y sin cita**.
2. Tras elegir uno, ofrece las próximas franjas con capacidad (inicio y fin).
3. Al elegir una, la reserva **vuelve a validar** propiedad, levante y
   capacidad dentro de una transacción (§11.3 paso 4) y confirma con
   contenedor, fecha, inicio y fin. Esa confirmación es el aviso 3 de §15.3
   («cita asignada»): se guarda en ``notificacion`` ya entregada.

Los botones llevan ``callback_data`` corto (``c:<manifiesto>``,
``f:<fecha>|<inicio>``) y solo se aceptan si estaban entre los ofrecidos.
"""

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from mensajeria.conversaciones import ConversacionCita, PasoCita, RegistroConversaciones
from mensajeria.formato import fecha_legible
from mensajeria.modelos import Boton, PulsacionBoton, Respuesta
from mensajeria.redactor import redactar
from mensajeria.textos import (
    MOTIVO_RESERVA_TEXTO,
    TEXTO_CONVERSACION_VENCIDA,
    TEXTO_ELIGE_CONTENEDOR,
    TEXTO_ELIGE_FRANJA,
    TEXTO_SIN_CITABLES,
    TEXTO_SIN_FRANJAS,
    TIPO_OP_TEXTO,
)
from web.modelos.cita import (
    FranjaOfrecida,
    fechas_de_ofrecimiento,
    fin_de_franja,
    franjas_ofrecibles,
)
from web.modelos.notificacion import TipoNotificacion
from web.repositorios.repositorio_citas import (
    MOTIVO_FRANJA_BLOQUEADA,
    MOTIVO_FRANJA_SIN_CAPACIDAD,
    RepositorioCitas,
)
from web.repositorios.repositorio_notificaciones import RepositorioNotificaciones
from web.tiempo import marca_utc

PREFIJO_CONTENEDOR = "c:"
PREFIJO_FRANJA = "f:"
PATRON_DATO_CONTENEDOR = re.compile(r"^c:(\d{1,9})$")
PATRON_DATO_FRANJA = re.compile(r"^f:(\d{4}-\d{2}-\d{2})\|(\d{2}:\d{2})$")
"""Validación estricta del ``callback_data`` en la frontera (S-2)."""
CONTENEDORES_OFRECIDOS_MAXIMOS = 10
"""Botones del primer paso; más no caben cómodamente en la pantalla del teléfono."""
MOTIVOS_QUE_OFRECEN_OTRA_FRANJA = frozenset({MOTIVO_FRANJA_BLOQUEADA, MOTIVO_FRANJA_SIN_CAPACIDAD})


class FlujoCita:
    """Los tres pasos de ``/cita`` sobre el registro de conversaciones."""

    def __init__(
        self,
        citas: RepositorioCitas,
        notificaciones: RepositorioNotificaciones,
        conversaciones: RegistroConversaciones,
        fabrica_instante: Callable[[], datetime],
    ) -> None:
        self._citas = citas
        self._notificaciones = notificaciones
        self._conversaciones = conversaciones
        self._fabrica_instante = fabrica_instante

    def iniciar(self, id_chat: int, transportista_id: int) -> Respuesta:
        """Paso 1: contenedores propios con levante y sin cita (§11.1 reglas 3 y 4)."""
        citables = self._citas.contenedores_citables(transportista_id)[
            :CONTENEDORES_OFRECIDOS_MAXIMOS
        ]
        if not citables:
            self._conversaciones.cancelar(id_chat)
            return Respuesta(TEXTO_SIN_CITABLES)
        self._conversaciones.guardar(
            id_chat,
            ConversacionCita(
                paso=PasoCita.ESPERANDO_CONTENEDOR,
                transportista_id=transportista_id,
                actualizada=self._fabrica_instante(),
                contenedores={c.manifiesto_id: c.contenedor_id for c in citables},
            ),
        )
        botones = tuple(
            (
                Boton(
                    f"{c.contenedor_id} · {TIPO_OP_TEXTO.get(c.tipo_op, c.tipo_op)}",
                    f"{PREFIJO_CONTENEDOR}{c.manifiesto_id}",
                ),
            )
            for c in citables
        )
        return Respuesta(TEXTO_ELIGE_CONTENEDOR, botones)

    def atender(self, pulsacion: PulsacionBoton, transportista_id: int) -> Respuesta:
        """Pasos 2 y 3 según el botón; cualquier dato fuera de lo ofrecido se rechaza."""
        conversacion = self._conversaciones.vigente(pulsacion.id_chat)
        if conversacion is None or conversacion.transportista_id != transportista_id:
            return Respuesta(TEXTO_CONVERSACION_VENCIDA)
        dato_contenedor = PATRON_DATO_CONTENEDOR.match(pulsacion.dato)
        if dato_contenedor and conversacion.paso is PasoCita.ESPERANDO_CONTENEDOR:
            return self._elegir_contenedor(
                pulsacion.id_chat, conversacion, int(dato_contenedor.group(1))
            )
        dato_franja = PATRON_DATO_FRANJA.match(pulsacion.dato)
        if dato_franja and conversacion.paso is PasoCita.ESPERANDO_FRANJA:
            franja = (dato_franja.group(1), dato_franja.group(2))
            return self._elegir_franja(pulsacion.id_chat, conversacion, franja)
        return Respuesta(TEXTO_CONVERSACION_VENCIDA)

    def _elegir_contenedor(
        self, id_chat: int, conversacion: ConversacionCita, manifiesto_id: int
    ) -> Respuesta:
        """Paso 2: próximas franjas con capacidad para el contenedor elegido."""
        contenedor = conversacion.contenedores.get(manifiesto_id)
        if contenedor is None:
            return Respuesta(TEXTO_CONVERSACION_VENCIDA)
        elegida = replace(conversacion, manifiesto_id=manifiesto_id, contenedor_id=contenedor)
        return self._ofrecer_franjas(id_chat, elegida, "")

    def _ofrecer_franjas(
        self, id_chat: int, conversacion: ConversacionCita, aviso_previo: str
    ) -> Respuesta:
        ahora = self._fabrica_instante()
        franjas = franjas_ofrecibles(ahora, self._citas.ocupacion(fechas_de_ofrecimiento(ahora)))
        if not franjas:
            self._conversaciones.cancelar(id_chat)
            return Respuesta(TEXTO_SIN_FRANJAS)
        self._conversaciones.guardar(
            id_chat,
            replace(
                conversacion,
                paso=PasoCita.ESPERANDO_FRANJA,
                actualizada=ahora,
                franjas=frozenset((f.fecha, f.inicio) for f in franjas),
            ),
        )
        texto = TEXTO_ELIGE_FRANJA.format(contenedor=conversacion.contenedor_id)
        if aviso_previo:
            texto = f"{aviso_previo}\n{texto}"
        return Respuesta(texto, tuple((_boton_franja(f),) for f in franjas))

    def _elegir_franja(
        self, id_chat: int, conversacion: ConversacionCita, franja: tuple[str, str]
    ) -> Respuesta:
        """Paso 3: reserva con revalidación y confirmación (aviso 3 de §15.3)."""
        if franja not in conversacion.franjas or conversacion.manifiesto_id is None:
            return Respuesta(TEXTO_CONVERSACION_VENCIDA)
        fecha, inicio = franja
        ts = marca_utc(self._fabrica_instante())
        reserva = self._citas.reservar(
            conversacion.manifiesto_id, conversacion.transportista_id, fecha, inicio, ts
        )
        if reserva.cita_id is None:
            aviso = MOTIVO_RESERVA_TEXTO.get(reserva.motivo, reserva.motivo)
            if reserva.motivo in MOTIVOS_QUE_OFRECEN_OTRA_FRANJA:
                return self._ofrecer_franjas(id_chat, conversacion, aviso)
            self._conversaciones.cancelar(id_chat)
            return Respuesta(aviso)
        self._conversaciones.cancelar(id_chat)
        payload: dict[str, object] = {
            "cita": reserva.cita_id,
            "contenedor": conversacion.contenedor_id,
            "fecha": fecha,
            "inicio": inicio,
            "fin": fin_de_franja(inicio),
        }
        tipo = TipoNotificacion.CITA_ASIGNADA
        self._notificaciones.crear(
            conversacion.transportista_id, tipo.value, payload, ts, entregado=True
        )
        return Respuesta(redactar(tipo.value, payload))


def _boton_franja(franja: FranjaOfrecida) -> Boton:
    dia = fecha_legible(franja.fecha)[:5]
    return Boton(
        f"{dia} · {franja.inicio} a {franja.fin}",
        f"{PREFIJO_FRANJA}{franja.fecha}|{franja.inicio}",
    )
