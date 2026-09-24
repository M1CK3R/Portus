"""Enclavamientos de los 13 comandos remotos, en el simulador (SPECS §6.1, §6.2).

Referencia ejecutable de lo que el firmware debe hacer: con la condición de
rechazo presente responde NAK con la causa exacta de §6.5 y **no cambia nada**;
sin ella responde ACK y aplica el efecto. Es lógica pura sobre
:class:`EstadoFisico` (sin puerto ni hilos) para probar comando por comando
que ninguno se ejecuta cuando se cumple su condición (§6.2 regla 5, penalización del 10 %).
Los sensores se fijan desde la consola del simulador (``sensor ...``).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

GRUA_REPOSO = "REPOSO"
GRUA_SUSPENDIDA = "SUSPENDIDA"
GRUA_FALLA = "FALLA"
MODO_NORMAL = "NORMAL"
MODO_MANTENIMIENTO = "MANTENIMIENTO"
VALOR_ACTIVAR = "ACTIVAR"

SENSORES = (
    "talanquera",
    "puerta",
    "aguja",
    "transferencia",
    "carga",
    "falla",
    "parqueo",
    "espera",
    "trabajo",
    "inconsistencia",
)
"""Nombres que acepta ``sensor NOMBRE VALOR`` en la consola del simulador."""


@dataclass
class EstadoFisico:
    """Lo que el controlador sabe de la maqueta: sensores y actuadores."""

    vehiculo_bajo_talanquera: bool = False
    vehiculo_bajo_puerta: bool = False
    vehiculo_sobre_aguja: bool = False
    vehiculo_en_transferencia: bool = False
    grua_con_carga: bool = False
    grua_en_falla: bool = False
    grua_suspendida: bool = False
    vehiculos_en_parqueo: int = 0
    vehiculos_en_espera: int = 0
    """Fila de la zona de espera: viaja en el latido ``EST espera`` (A15, métrica 6)."""
    posiciones_en_trabajo: set[str] = field(default_factory=set)
    """Origen y destino del trabajo de grúa en ejecución; vacío si no hay."""
    inconsistencias: set[str] = field(default_factory=set)
    """Posiciones cuya inconsistencia física persiste (bloqueo de §6.1 #11)."""
    mantenimiento: bool = False
    talanquera_abierta: bool = False
    puerta_abierta: bool = False
    aguja: str = "RECTA"
    posiciones_bloqueadas: set[str] = field(default_factory=set)
    silencio: bool = False

    @property
    def trabajo_en_ejecucion(self) -> bool:
        return bool(self.posiciones_en_trabajo)

    @property
    def estado_grua(self) -> str:
        """Valor ``grua`` del latido (docs/protocolo_serial.md §3.1.1)."""
        if self.grua_en_falla:
            return GRUA_FALLA
        if self.grua_suspendida:
            return GRUA_SUSPENDIDA
        return GRUA_REPOSO


Regla = Callable[[dict[str, str], "EstadoFisico"], str | None]
Efecto = Callable[[dict[str, str], "EstadoFisico"], None]


def _si(condicion: bool, causa: str) -> str | None:
    return causa if condicion else None


def _rechazo_aguja_liberar(parametros: dict[str, str], fisico: EstadoFisico) -> str | None:
    sin_vehiculo = fisico.vehiculos_en_parqueo == 0 or not parametros.get("plaza")
    return _si(fisico.vehiculo_sobre_aguja, "VEH_SOBRE_AGUJA") or _si(sin_vehiculo, "PARQUEO_VACIO")


def _rechazo_mantenimiento(parametros: dict[str, str], fisico: EstadoFisico) -> str | None:
    del parametros
    return _si(fisico.trabajo_en_ejecucion, "GRUA_EN_TRABAJO") or _si(
        fisico.vehiculo_en_transferencia, "VEH_EN_TRANSFERENCIA"
    )


REGLAS_DE_RECHAZO: dict[str, Regla] = {
    "AbrirTalanquera": lambda _, f: _si(f.vehiculo_bajo_talanquera, "VEH_BAJO_TALANQUERA"),
    "CerrarTalanquera": lambda _, f: _si(f.vehiculo_bajo_talanquera, "VEH_BAJO_TALANQUERA"),
    "AbrirPuertaSalida": lambda _, f: _si(f.vehiculo_bajo_puerta, "VEH_BAJO_PUERTA"),
    "AgujaRecta": lambda _, f: _si(f.vehiculo_sobre_aguja, "VEH_SOBRE_AGUJA"),
    "AgujaParqueo": lambda _, f: _si(f.vehiculo_sobre_aguja, "VEH_SOBRE_AGUJA"),
    "AgujaLiberar": _rechazo_aguja_liberar,
    "GruaReferenciar": lambda _, f: (
        _si(f.grua_con_carga, "GRUA_CON_CARGA") or _si(f.trabajo_en_ejecucion, "GRUA_EN_TRABAJO")
    ),
    "GruaReanudar": lambda _, f: _si(f.grua_en_falla, "GRUA_EN_FALLA"),
    "PosicionBloquear": lambda p, f: _si(p.get("pos") in f.posiciones_en_trabajo, "POS_EN_TRABAJO"),
    "PosicionLiberar": lambda p, f: _si(
        p.get("pos") in f.inconsistencias, "INCONSISTENCIA_PERSISTE"
    ),
    "ModoMantenimiento": _rechazo_mantenimiento,
}
"""Tabla §6.1: GruaSuspender y AlarmaSilenciar no figuran porque nunca se rechazan."""


def evaluar_comando(nombre: str, parametros: dict[str, str], fisico: EstadoFisico) -> str | None:
    """Causa de rechazo de §6.1 si la condición está presente; None si se acepta."""
    regla = REGLAS_DE_RECHAZO.get(nombre)
    return regla(parametros, fisico) if regla is not None else None


def _mover_aguja(destino: str, delta_parqueo: int) -> Efecto:
    def efecto(parametros: dict[str, str], fisico: EstadoFisico) -> None:
        del parametros
        fisico.aguja = destino
        fisico.vehiculos_en_parqueo += delta_parqueo

    return efecto


def _fijar(atributo: str, valor: object) -> Efecto:
    def efecto(parametros: dict[str, str], fisico: EstadoFisico) -> None:
        del parametros
        setattr(fisico, atributo, valor)

    return efecto


EFECTOS: dict[str, Efecto] = {
    "AbrirTalanquera": _fijar("talanquera_abierta", True),
    "CerrarTalanquera": _fijar("talanquera_abierta", False),
    "AbrirPuertaSalida": _fijar("puerta_abierta", True),
    "AgujaRecta": _mover_aguja("RECTA", 0),
    "AgujaParqueo": _mover_aguja("PARQUEO", 1),
    "AgujaLiberar": _mover_aguja("LIBERANDO", -1),
    "GruaSuspender": _fijar("grua_suspendida", True),
    "GruaReanudar": _fijar("grua_suspendida", False),
    "PosicionBloquear": lambda p, f: f.posiciones_bloqueadas.add(p.get("pos", "")),
    "PosicionLiberar": lambda p, f: f.posiciones_bloqueadas.discard(p.get("pos", "")),
    "ModoMantenimiento": lambda p, f: setattr(f, "mantenimiento", p.get("valor") == VALOR_ACTIVAR),
    "AlarmaSilenciar": _fijar("silencio", True),
}
"""Efecto de cada comando aceptado; GruaReferenciar deja la grúa en reposo (sin cambio)."""


def aplicar_efecto(nombre: str, parametros: dict[str, str], fisico: EstadoFisico) -> None:
    """Efecto físico de un comando **aceptado** (solo se llama tras un ACK)."""
    efecto = EFECTOS.get(nombre)
    if efecto is not None:
        efecto(parametros, fisico)


SENSORES_BOOLEANOS = {
    "talanquera": "vehiculo_bajo_talanquera",
    "puerta": "vehiculo_bajo_puerta",
    "aguja": "vehiculo_sobre_aguja",
    "transferencia": "vehiculo_en_transferencia",
    "carga": "grua_con_carga",
    "falla": "grua_en_falla",
}


def fijar_sensor(nombre: str, valor: str, fisico: EstadoFisico) -> None:
    """Orden ``sensor NOMBRE VALOR`` de la consola; ValueError si no se reconoce.

    Booleanos con 1/0; ``parqueo`` y ``espera`` con cantidad de vehículos; ``trabajo``
    e ``inconsistencia`` con una posición (``P3``) o ``0`` para vaciar.
    """
    activo = valor not in ("0", "no", "")
    if nombre in SENSORES_BOOLEANOS:
        setattr(fisico, SENSORES_BOOLEANOS[nombre], activo)
    elif nombre == "parqueo":
        fisico.vehiculos_en_parqueo = int(valor)
    elif nombre == "espera":
        fisico.vehiculos_en_espera = max(0, int(valor))
    elif nombre == "trabajo":
        fisico.posiciones_en_trabajo = {valor} if activo else set()
    elif nombre == "inconsistencia" and activo:
        fisico.inconsistencias.add(valor)
    elif nombre == "inconsistencia":
        fisico.inconsistencias.clear()
    else:
        mensaje = f"sensor desconocido '{nombre}' (use: {', '.join(SENSORES)})"
        raise ValueError(mensaje)


def resumen(fisico: EstadoFisico) -> str:
    """Una línea con el estado físico para la orden ``estado`` de la consola."""
    return (
        f"talanquera={'veh' if fisico.vehiculo_bajo_talanquera else '-'}"
        f"/{'abierta' if fisico.talanquera_abierta else 'cerrada'} "
        f"puerta={'veh' if fisico.vehiculo_bajo_puerta else '-'} "
        f"aguja={fisico.aguja}{'+veh' if fisico.vehiculo_sobre_aguja else ''} "
        f"parqueo={fisico.vehiculos_en_parqueo} "
        f"espera={fisico.vehiculos_en_espera} "
        f"transferencia={'veh' if fisico.vehiculo_en_transferencia else '-'} "
        f"grua={fisico.estado_grua}{'+carga' if fisico.grua_con_carga else ''} "
        f"trabajo={sorted(fisico.posiciones_en_trabajo) or '-'} "
        f"inconsistencias={sorted(fisico.inconsistencias) or '-'} "
        f"bloqueadas={sorted(fisico.posiciones_bloqueadas) or '-'} "
        f"mantenimiento={'sí' if fisico.mantenimiento else 'no'}"
    )
