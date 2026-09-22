"""Fuentes de tiempo del puente (CODESTYLE D-9).

Única fuente de ``reloj_monotonico_ms``: los intervalos (tiempos límite de
comandos, umbrales del vigilante, arranque del proceso) se miden con reloj
monotónico para no depender de saltos del reloj de pared; las marcas de
tiempo de negocio siguen siendo UTC (CODESTYLE I-8).
"""

import time

MS_POR_SEGUNDO = 1000


def reloj_monotonico_ms() -> int:
    """Reloj monotónico en ms para medir intervalos (CODESTYLE D-9)."""
    return int(time.monotonic() * MS_POR_SEGUNDO)
