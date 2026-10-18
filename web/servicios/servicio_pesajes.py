"""Pesaje en el servidor: revalida la tolerancia y mueve la ruta (SPECS A4, A5, §9.2).

El controlador compara en línea con los datos de ``AUT`` (A5) y reporta
``PES``; el servidor **revalida** con la fórmula documentada y decide RT01,
RT02 y AL09. Fórmula [DEC A4], con la tara por vehículo:

* DEPOSITO — entrada: ``neto = medido - tara`` contra el declarado;
  salida: ``medido`` contra la tara (el camión sale sin contenedor).
* RETIRO — entrada: ``medido`` contra la tara (llega vacío); salida:
  ``neto = medido - tara`` contra el declarado.

``hay_discrepancia = diferencia_pct > tolerancia_pct`` (§10.4, 5 % por
omisión). Canal rojo → RT03 inmediatamente después del pesaje de entrada
(§9.2). Los pesajes y datos acumulados se conservan al retener (§8.2 regla 3).
"""

import logging
from collections.abc import Callable
from datetime import datetime

from web.modelos.alarma import CodigoAlarma
from web.modelos.datos_manifiesto import DatosManifiesto
from web.modelos.retencion import CausaRetencion, calcular_diferencia_pct
from web.modelos.turno import EstadoTurno, Turno
from web.repositorios.repositorio_manifiestos import RepositorioManifiestos
from web.repositorios.repositorio_pesajes import RepositorioPesajes
from web.repositorios.repositorio_turnos import RepositorioTurnos
from web.repositorios.repositorio_vehiculos import RepositorioVehiculos
from web.servicios.emisor_alarmas import EmisorAlarmas
from web.servicios.puertos import PublicadorLogica
from web.servicios.servicio_retenciones import ServicioRetenciones
from web.servicios.servicio_turnos import ServicioTurnos
from web.tiempo import marca_utc

REGISTRO = logging.getLogger(__name__)


PESO_DE_TARA = "tara"
PESO_NETO = "neto"
ESTACION_PESAJE_ENTRADA = "pesaje_entrada"
ESTACION_PESAJE_SALIDA = "pesaje_salida"


class ServicioPesajes:
    """Revalidación A5 del pesaje confirmado por el controlador."""

    def __init__(
        self,
        vehiculos: RepositorioVehiculos,
        manifiestos: RepositorioManifiestos,
        turnos_repo: RepositorioTurnos,
        pesajes: RepositorioPesajes,
        maquina: ServicioTurnos,
        retenciones: ServicioRetenciones,
        publicador: PublicadorLogica,
        fabrica_instante: Callable[[], datetime],
        alarmas: EmisorAlarmas,
    ) -> None:
        self._vehiculos = vehiculos
        self._manifiestos = manifiestos
        self._turnos_repo = turnos_repo
        self._pesajes = pesajes
        self._maquina = maquina
        self._retenciones = retenciones
        self._publicador = publicador
        self._fabrica_instante = fabrica_instante
        self._alarmas = alarmas

    def procesar_pesaje(
        self, identificador: str, peso_g: int, muestras: int, meseta: bool, seq: int | None
    ) -> None:
        """Atiende un PES confirmado según el estado del turno del vehículo (§8.1)."""
        if peso_g < 0:
            REGISTRO.warning(
                "PES con peso negativo (%d) para '%s'; se descarta", peso_g, identificador
            )
            return
        vehiculo = self._vehiculos.buscar_por_identificador(identificador)
        if vehiculo is None:
            REGISTRO.warning("PES de vehículo desconocido '%s'; se descarta (P-5)", identificador)
            return
        turno = self._turnos_repo.activo_de_vehiculo(vehiculo.id)
        if turno is None:
            REGISTRO.warning("PES de '%s' sin turno activo; se descarta (P-5)", identificador)
            return
        match turno.estado:
            case EstadoTurno.EN_GARITA:
                self._pesaje_entrada(turno, peso_g, muestras, meseta, seq)
            case EstadoTurno.EN_PESAJE_SALIDA:
                self._pesaje_salida(turno, peso_g, muestras, meseta, seq)
            case _:
                REGISTRO.warning(
                    "PES de '%s' con turno en estado %s fuera de plataforma; se descarta (P-5)",
                    identificador,
                    turno.estado.value,
                )

    # --------------------------------------------------------------- entrada

    def _pesaje_entrada(
        self, turno: Turno, peso_g: int, muestras: int, meseta: bool, seq: int | None
    ) -> None:
        """EnGarita → EnPesajeEntrada; revalida (RT01/RT03) y sigue a EnRuta (§8.1)."""
        datos = self._datos(turno)
        referencia_g, modo = self._referencia(turno, entrada=True)
        comparado_g = peso_g - self._tara(turno) if modo == PESO_NETO else peso_g
        dentro = self._dentro_de_tolerancia(comparado_g, referencia_g, datos)
        ts = marca_utc(self._fabrica_instante())
        self._pesajes.guardar(turno.id, "entrada", peso_g, muestras, meseta, dentro, ts)
        turno = self._registrar_peso(turno, peso_g, seq, entrada=True)
        if not dentro:
            self._retener_por_peso(
                turno,
                CausaRetencion.RT01,
                ESTACION_PESAJE_ENTRADA,
                datos,
                comparado_g,
                referencia_g,
                "Discrepancia de peso al ingreso",
                seq,
            )
            return
        if turno.canal == "rojo":
            # Canal rojo: ingresa y pasa al parqueo tras el pesaje de entrada (§9.2).
            self._retenciones.retener(
                turno,
                CausaRetencion.RT03,
                ESTACION_PESAJE_ENTRADA,
                peso_declarado_g=referencia_g,
                peso_medido_g=comparado_g,
                observacion="Canal rojo de selectivo",
            )
            return
        self._maquina.transicionar(
            turno,
            EstadoTurno.EN_RUTA,
            "Pesaje de entrada dentro de tolerancia: continúa a la zona de transferencia",
            {"peso_g": peso_g},
            origen="controlador",
            seq=seq,
        )

    # ---------------------------------------------------------------- salida

    def _pesaje_salida(
        self, turno: Turno, peso_g: int, muestras: int, meseta: bool, seq: int | None
    ) -> None:
        """EnPesajeSalida: revalida (RT02) y pasa a EnSalida (§8.1)."""
        datos = self._datos(turno)
        referencia_g, modo = self._referencia(turno, entrada=False)
        comparado_g = peso_g - self._tara(turno) if modo == PESO_NETO else peso_g
        dentro = self._dentro_de_tolerancia(comparado_g, referencia_g, datos)
        ts = marca_utc(self._fabrica_instante())
        self._pesajes.guardar(turno.id, "salida", peso_g, muestras, meseta, dentro, ts)
        turno = self._registrar_peso(turno, peso_g, seq, entrada=False)
        if not dentro:
            self._retener_por_peso(
                turno,
                CausaRetencion.RT02,
                ESTACION_PESAJE_SALIDA,
                datos,
                comparado_g,
                referencia_g,
                "Discrepancia de peso a la salida",
                seq,
            )
            return
        self._maquina.transicionar(
            turno,
            EstadoTurno.EN_SALIDA,
            "Pesaje de salida dentro de tolerancia: espera autorización de salida",
            {"peso_g": peso_g},
            origen="controlador",
            seq=seq,
        )

    # -------------------------------------------------------------- fórmulas

    def _referencia(self, turno: Turno, entrada: bool) -> tuple[int, str]:
        """(referencia, modo) del pesaje según la operación y el momento (A4 [DEC])."""
        if entrada == (turno.tipo_op == "DEPOSITO"):
            return (self._datos(turno).peso_declarado_g, PESO_NETO)
        return (self._tara(turno), PESO_DE_TARA)

    def _dentro_de_tolerancia(
        self, comparado_g: int, referencia_g: int, datos: DatosManifiesto
    ) -> bool:
        """Revalidación A5 con la fórmula §10.4 y la tolerancia del manifiesto."""
        diferencia_pct = calcular_diferencia_pct(comparado_g, referencia_g)
        dentro = diferencia_pct <= datos.tolerancia_pct
        if not dentro:
            self._alarmar_al09(referencia_g, comparado_g, diferencia_pct)
        return dentro

    def _alarmar_al09(self, referencia_g: int, comparado_g: int, diferencia_pct: float) -> None:
        """AL09 (media, origen servidor) persistida y publicada (§13.1, §13.2)."""
        self._alarmas.emitir(
            CodigoAlarma.AL09,
            {
                "referencia_g": referencia_g,
                "comparado_g": comparado_g,
                "diferencia_pct": round(diferencia_pct, 2),
            },
        )

    # -------------------------------------------------------------- elementos

    def _registrar_peso(self, turno: Turno, peso_g: int, seq: int | None, entrada: bool) -> Turno:
        """Guarda el peso en el turno y completa la transición a la plataforma (§8.1)."""
        if entrada and turno.estado is EstadoTurno.EN_GARITA:
            turno = self._maquina.transicionar(
                turno,
                EstadoTurno.EN_PESAJE_ENTRADA,
                "Vehículo sobre la plataforma de pesaje de entrada",
                {"peso_g": peso_g},
                origen="controlador",
                seq=seq,
            )
        self._turnos_repo.actualizar_datos(
            turno.id, {"peso_entrada_g" if entrada else "peso_salida_g": peso_g}
        )
        return self._maquina.buscar_turno(turno.id) or turno

    def _retener_por_peso(
        self,
        turno: Turno,
        causa: CausaRetencion,
        estacion: str,
        datos: DatosManifiesto,
        comparado_g: int,
        referencia_g: int,
        observacion: str,
        seq: int | None,
    ) -> None:
        """RT01/RT02 con evidencia de peso y AL09 ya emitida (§10.2, §10.4)."""
        _ = seq
        self._retenciones.retener(
            turno,
            causa,
            estacion,
            peso_declarado_g=referencia_g,
            peso_medido_g=comparado_g,
            observacion=observacion,
        )
        REGISTRO.warning(
            "Turno %d: %s (comparado=%d g, declarado=%d g, tolerancia=%.1f%%)",
            turno.id,
            causa.value,
            comparado_g,
            referencia_g,
            datos.tolerancia_pct,
        )

    def _tara(self, turno: Turno) -> int:
        vehiculo = self._vehiculos.buscar_por_id(turno.vehiculo_id)
        return vehiculo.tara_g if vehiculo is not None else 0

    def _datos(self, turno: Turno) -> DatosManifiesto:
        """Peso declarado y tolerancia del manifiesto del turno (A5)."""
        manifiesto = self._manifiestos.buscar_por_id(turno.manifiesto_id)
        if manifiesto is None:
            mensaje = f"el turno {turno.id} apunta al manifiesto inexistente {turno.manifiesto_id}"
            raise RuntimeError(mensaje)
        return DatosManifiesto(
            peso_declarado_g=manifiesto.peso_declarado_g, tolerancia_pct=manifiesto.tolerancia_pct
        )
