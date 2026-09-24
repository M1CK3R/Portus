"""Formato de fechas, duraciones, pesos y longitud de los mensajes (SPECS §15.4).

Las horas se muestran en la hora de la terminal (UTC-6, la misma de las
franjas, I-8). Telegram admite hasta 4096 caracteres por mensaje: las listas
largas se recortan con un aviso de cuántos elementos quedaron fuera.
"""

from datetime import datetime

from web.modelos.cita import ZONA_LOCAL
from web.tiempo import instante_de_marca

LARGO_MAXIMO_MENSAJE = 4096
"""Límite de ``sendMessage`` de Telegram (§15.4 «Tamaño»)."""
ELEMENTOS_MAXIMOS_LISTA = 15
"""Tope de filas en /miscitas y /misturnos antes de resumir el resto."""
MARCA_RECORTE = "…"
SEGUNDOS_POR_MINUTO = 60
MINUTOS_POR_HORA = 60


def fecha_legible(fecha: str) -> str:
    """``2026-09-24`` → ``24/09/2026``."""
    anio, mes, dia = fecha.split("-")
    return f"{dia}/{mes}/{anio}"


def marca_legible(marca: str) -> str:
    """Marca UTC del proyecto → ``24/09/2026 10:15`` en hora de la terminal."""
    local = instante_de_marca(marca).astimezone(ZONA_LOCAL)
    return local.strftime("%d/%m/%Y %H:%M")


def duracion_legible(segundos: float) -> str:
    """Duración en horas y minutos (§15.2 «reloj de permanencia (h y min)»)."""
    minutos_totales = max(0, int(segundos // SEGUNDOS_POR_MINUTO))
    horas, minutos = divmod(minutos_totales, MINUTOS_POR_HORA)
    return f"{horas} h {minutos:02d} min"


def permanencia_desde(marca_ingreso: str, ahora: datetime) -> str:
    """Tiempo transcurrido desde el ingreso al patio hasta ``ahora``."""
    return duracion_legible((ahora - instante_de_marca(marca_ingreso)).total_seconds())


def peso_legible(gramos: object) -> str:
    """Peso en gramos con separador de miles (la maqueta pesa en gramos, N-2)."""
    if isinstance(gramos, bool) or not isinstance(gramos, int | float):
        return "—"
    return f"{int(gramos):,} g".replace(",", " ")


def recortar(texto: str) -> str:
    """Garantiza el límite de 4096 caracteres de Telegram."""
    if len(texto) <= LARGO_MAXIMO_MENSAJE:
        return texto
    return texto[: LARGO_MAXIMO_MENSAJE - len(MARCA_RECORTE)] + MARCA_RECORTE


def lista_con_tope(encabezado: str, bloques: list[str]) -> str:
    """Une los bloques bajo un encabezado, con tope de filas y de caracteres."""
    visibles = bloques[:ELEMENTOS_MAXIMOS_LISTA]
    texto = encabezado + "\n\n" + "\n\n".join(visibles)
    restantes = len(bloques) - len(visibles)
    if restantes > 0:
        texto += f"\n\n… y {restantes} más."
    return recortar(texto)
