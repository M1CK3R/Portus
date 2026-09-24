"""Retenciones (SPECS §10.2, §10.3): causas RT01-RT06, roles facultados y resoluciones."""

from dataclasses import dataclass
from enum import StrEnum

from web.modelos.usuario import Rol


class CausaRetencion(StrEnum):
    """Las seis causas exactas del SPECS §10.2."""

    RT01 = "RT01"
    RT02 = "RT02"
    RT03 = "RT03"
    RT04 = "RT04"
    RT05 = "RT05"
    RT06 = "RT06"


@dataclass(frozen=True)
class DefinicionCausa:
    """Fila de la tabla §10.2: cuándo se genera y quién la resuelve."""

    codigo: CausaRetencion
    rol_facultado: Rol
    origen: str
    """«operativo» o «aduanero»: la bandeja de AUTORIDAD lista solo aduaneras."""
    descripcion: str


DEFINICIONES_CAUSA: dict[CausaRetencion, DefinicionCausa] = {
    CausaRetencion.RT01: DefinicionCausa(
        CausaRetencion.RT01, Rol.TERMINAL, "operativo", "Discrepancia de peso al ingreso"
    ),
    CausaRetencion.RT02: DefinicionCausa(
        CausaRetencion.RT02, Rol.TERMINAL, "operativo", "Discrepancia de peso a la salida"
    ),
    CausaRetencion.RT03: DefinicionCausa(
        CausaRetencion.RT03, Rol.AUTORIDAD, "aduanero", "Canal rojo de selectivo"
    ),
    CausaRetencion.RT04: DefinicionCausa(
        CausaRetencion.RT04, Rol.TERMINAL, "operativo", "Llegada fuera de la ventana asignada"
    ),
    CausaRetencion.RT05: DefinicionCausa(
        CausaRetencion.RT05, Rol.AUTORIDAD, "aduanero", "Retención documental"
    ),
    CausaRetencion.RT06: DefinicionCausa(
        CausaRetencion.RT06, Rol.TERMINAL, "operativo", "Retención manual operativa"
    ),
}

CAUSAS_ADUANERAS: frozenset[CausaRetencion] = frozenset({CausaRetencion.RT03, CausaRetencion.RT05})
"""Las que la pestaña de retenciones aduaneras lista (§10.2, §14 AUTORIDAD)."""

CAUSAS_DE_PESO: frozenset[CausaRetencion] = frozenset({CausaRetencion.RT01, CausaRetencion.RT02})
"""Únicas con evidencia de peso y con sentido para Corregir (A12, §10.4)."""

CAUSAS_ORDENABLES: frozenset[CausaRetencion] = frozenset({CausaRetencion.RT05, CausaRetencion.RT06})
"""Las que un usuario ordena «en cualquier momento» (§10.2); las demás las detecta el sistema."""


class ResolucionRetencion(StrEnum):
    """Las tres resoluciones exactas del SPECS §10.3."""

    ACLARAR = "ACLARAR"
    CORREGIR = "CORREGIR"
    RECHAZAR = "RECHAZAR"


def rol_facultado(causa: CausaRetencion) -> Rol:
    """Rol que puede resolver una retención de la causa dada (§10.2, §7.5.3)."""
    return DEFINICIONES_CAUSA[causa].rol_facultado


def puede_resolver(rol: Rol, causa: CausaRetencion, resolucion: ResolucionRetencion) -> bool:
    """Aplica §10.2 (rol facultado) y §10.3 (Corregir: solo TERMINAL y solo peso, A12)."""
    if rol is not rol_facultado(causa):
        return False
    if resolucion is ResolucionRetencion.CORREGIR:
        return rol is Rol.TERMINAL and causa in CAUSAS_DE_PESO
    return True


def compara_con_manifiesto(causa: CausaRetencion, tipo_op: str) -> bool:
    """True si el pesaje de esa causa se comparó con el peso del manifiesto (A4 [DEC]).

    DEPOSITO entra cargado (RT01 contra el manifiesto) y sale vacío (RT02
    contra la tara); RETIRO al revés. Corregir solo tiene sentido contra el
    manifiesto: contra la tara sustituiría el peso del contenedor por el del
    camión vacío.
    """
    return (causa is CausaRetencion.RT01 and tipo_op == "DEPOSITO") or (
        causa is CausaRetencion.RT02 and tipo_op == "RETIRO"
    )


def puede_ordenar(rol: Rol, causa: CausaRetencion) -> bool:
    """RT05 la ordena solo AUTORIDAD y RT06 solo TERMINAL (§10.2, A9)."""
    return causa in CAUSAS_ORDENABLES and rol is rol_facultado(causa)


def calcular_diferencia_pct(peso_medido_g: int, peso_declarado_g: int) -> float:
    """Diferencia porcentual respecto al peso declarado (SPECS §10.4)."""
    if peso_declarado_g <= 0:
        mensaje = f"peso_declarado_g debe ser mayor que 0 (recibido: {peso_declarado_g})"
        raise ValueError(mensaje)
    return abs(peso_medido_g - peso_declarado_g) / peso_declarado_g * 100


@dataclass(frozen=True)
class Retencion:
    """Fila de ``retencion`` del dominio (§17.1); el consecutivo único es ``id``."""

    id: int
    turno_id: int
    causa: CausaRetencion
    estacion: str
    plaza: int | None
    estado: str
    peso_declarado_g: int | None = None
    peso_medido_g: int | None = None
    resolucion: str | None = None
    motivo: str | None = None
    observacion: str | None = None
    resuelta_por: int | None = None
    creada_en: str = ""
    resuelta_en: str | None = None


@dataclass(frozen=True)
class EvidenciaPeso:
    """Evidencia de peso de RT01/RT02 con las fórmulas del §10.4."""

    peso_declarado_g: int
    peso_medido_g: int
    diferencia_abs_g: int
    diferencia_pct: float


@dataclass(frozen=True)
class FilaBandejaRetencion:
    """Fila de la bandeja §14.3: la retención con su turno, vehículo, contenedor y rol."""

    retencion: Retencion
    vehiculo: str
    contenedor_id: str
    rol_facultado: Rol
    evidencia: EvidenciaPeso | None
    corregible: bool
    """Corregir aplica: causa de peso comparada con el manifiesto (A12, A4)."""


def evidencia_de(retencion: Retencion) -> EvidenciaPeso | None:
    """Evidencia §10.4 solo para causas de peso con ambos pesos registrados."""
    declarado = retencion.peso_declarado_g
    medido = retencion.peso_medido_g
    if retencion.causa not in CAUSAS_DE_PESO or declarado is None or medido is None:
        return None
    if declarado <= 0:
        return None
    return EvidenciaPeso(
        peso_declarado_g=declarado,
        peso_medido_g=medido,
        diferencia_abs_g=abs(medido - declarado),
        diferencia_pct=round(calcular_diferencia_pct(medido, declarado), 2),
    )
