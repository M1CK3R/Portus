"""Servicios web de PORTUS: núcleo de autenticación, permisos e interfaz (Etapa 4).

Capas (CODESTYLE A-2): ``rutas`` → ``servicios`` → ``repositorios``. Los
servicios no importan Flask; los repositorios son el único lugar con SQL.
Se ejecuta con ``python -m web --config config/portus.env``.
"""
