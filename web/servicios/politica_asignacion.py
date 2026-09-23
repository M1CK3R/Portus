"""Política de asignación de posiciones del patio (SPECS §12.4).

La política de la **Fase 1 se conserva como modo seleccionable**: vive
detrás de la interfaz ``PoliticaAsignacion.asignar_posicion(...)`` y se
elige por configuración (``politica_asignacion = FASE1`` por omisión). Sin
esta línea base la Fase 3 no tiene contra qué comparar (§12.4, §16.3).
"""

from web.modelos.patio import CeldaInventario, ErrorPatio, EstadoDePosicion, PoliticaAsignacion

POLITICA_FASE1 = "FASE1"
POLITICA_POR_OMISION = POLITICA_FASE1
POLITICAS_DISPONIBLES = (POLITICA_FASE1,)
"""La optimizada de la Fase 3 se agrega aquí cuando exista (§12.4)."""


class PoliticaFase1:
    """Primera celda libre de menor posición y menor nivel (lógica de la Fase 1).

    Excluye las posiciones reservadas y bloqueadas y respeta el apilado a dos
    niveles: prefiere el nivel 1; el nivel 2 solo si el nivel 1 de esa
    posición está ocupado (el apilado exige apoyo debajo, §12.1).
    """

    def asignar_posicion(
        self,
        contenedor_id: str,
        inventario: tuple[CeldaInventario, ...],
        posiciones: tuple[EstadoDePosicion, ...],
    ) -> tuple[str, int]:
        del contenedor_id  # la Fase 1 no considera la identidad, solo el espacio
        ocupadas = {(celda.posicion, celda.nivel) for celda in inventario if celda.contenedor_id}
        for posicion in posiciones:
            if posicion.estado in ("reservada", "bloqueada"):
                continue
            for nivel in (1, 2):
                if nivel == 2 and (posicion.id, 1) not in ocupadas:
                    continue  # sin apoyo en nivel 1 no se apila (§12.1)
                if (posicion.id, nivel) not in ocupadas:
                    return (posicion.id, nivel)
        mensaje = "no hay celda libre apilable en el patio para la asignación FASE1"
        raise ErrorPatio(mensaje)


def crear_politica(nombre: str) -> PoliticaAsignacion:
    """Fábrica del modo seleccionable; la configuración elige (§12.4 [PROP])."""
    if nombre == POLITICA_FASE1:
        return PoliticaFase1()
    mensaje = (
        f"política de asignación desconocida: '{nombre}' (disponibles: {POLITICAS_DISPONIBLES})"
    )
    raise ValueError(mensaje)
