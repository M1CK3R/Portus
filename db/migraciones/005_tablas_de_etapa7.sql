-- 005_tablas_de_etapa7.sql — Etapa 7: cadena documental (SPECS §9, §14.7-§14.9).
-- Tabla de declaraciones de mercancías del AGENTE (§9.3): número único,
-- régimen, descripción ≥ 10, valor > 0, ligada al manifiesto y al agente.
-- Idempotente (CREATE TABLE IF NOT EXISTS) para correr en cada arranque (BD-2).

CREATE TABLE IF NOT EXISTS declaracion (
    id INTEGER PRIMARY KEY,
    manifiesto_id INTEGER NOT NULL REFERENCES manifiesto (id),
    agente_id INTEGER NOT NULL REFERENCES usuario (id),
    -- Número único de la declaración (§9.3: "único en el sistema").
    numero TEXT NOT NULL UNIQUE,
    -- Régimen exacto del SPECS §9.3.
    regimen TEXT NOT NULL CHECK (regimen IN ('IMPORTACION_DEFINITIVA', 'DEPOSITO_TEMPORAL')),
    descripcion TEXT NOT NULL CHECK (length(descripcion) >= 10),
    valor INTEGER NOT NULL CHECK (valor > 0),
    presentada_en TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_declaracion_manifiesto ON declaracion (manifiesto_id);
-- Justificación: el AGENTE y la AUTORIDAD consultan la declaración por manifiesto.

CREATE INDEX IF NOT EXISTS ix_declaracion_agente ON declaracion (agente_id);
-- Justificación: la pestaña Seguimiento lista las del agente en sesión.
