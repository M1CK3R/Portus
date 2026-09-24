"""Servicio de mensajería del transportista: bot de Telegram (SPECS §15; Etapa 10).

Proceso ``portus-msg`` (§19.2) con tres tareas concurrentes sin bloqueo cruzado
(CODESTYLE PY-4): el *long polling* de Telegram, la escucha MQTT de los
avisos ``portus/srv/*`` y el planificador de recordatorios.

Capas (A-2): ``adaptador_telegram`` es el **único** módulo que importa la
librería de Telegram y traduce sus nombres en inglés (I-4); ``servicio_bot``,
``despachador`` y ``recordatorios`` son lógica pura que recibe todo inyectado;
el SQL vive en ``web/repositorios`` (base compartida con la web).
Se ejecuta con ``python -m mensajeria --config config/portus.env``.
"""
