-- 008_inicio_de_trabajos_grua.sql — Etapa 12: datos de las métricas de §16.1.
-- Instante real de inicio de cada trabajo de grúa (métricas 1-3, gráfica §12.6).
-- El ciclo de grúa (§12.6) dura desde que el JOB se envía al controlador hasta
-- su FIN o ABORTO; ``trabajo_grua.creado_en`` es la hora en que se planificó
-- (al autorizar en garita), que puede ser muy anterior. Reenviar tras un
-- aborto reemplaza la marca: el ciclo nuevo empieza con el reenvío.
-- Tabla aparte porque el esquema se aplica en cada arranque (sin ALTER, BD-2).

CREATE TABLE IF NOT EXISTS inicio_trabajo_grua (
    trabajo_id INTEGER PRIMARY KEY REFERENCES trabajo_grua (id),
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_telemetria_tipo_ts ON telemetria (tipo, ts);
-- Justificación: la métrica 6 busca las muestras ``fila_espera`` del periodo y
-- la última anterior a su inicio (§16.1, A15); el latido llena la tabla.
