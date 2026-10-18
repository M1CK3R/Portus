-- 001_tablas_del_puente.sql
-- Migración inicial: tablas propias del puente serial (Etapa 3, SPECS §5.7, §17).
-- Las tablas del dominio (usuario, manifiesto, turno, ...) llegan con las
-- migraciones de la Etapa 4 y se agregan aquí en orden.

CREATE TABLE IF NOT EXISTS evento (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    origen TEXT NOT NULL,
    tipo TEXT NOT NULL,
    seq INTEGER,
    datos TEXT NOT NULL,
    topico TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS telemetria (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    tipo TEXT NOT NULL,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comando (
    cmd_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    usuario TEXT,
    nombre TEXT NOT NULL,
    parametros TEXT NOT NULL,
    estado TEXT,
    causa TEXT,
    seq INTEGER,
    tardia INTEGER NOT NULL DEFAULT 0 CHECK (tardia IN (0, 1))
);

CREATE TABLE IF NOT EXISTS estado_enlace (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    ultimo_latido_ts TEXT,
    enlace_estado TEXT NOT NULL,
    actualizado_en TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_evento_ts ON evento (ts);
CREATE INDEX IF NOT EXISTS ix_evento_tipo ON evento (tipo);
CREATE INDEX IF NOT EXISTS ix_telemetria_ts ON telemetria (ts);
