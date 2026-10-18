-- 006_alertas_periodicas.sql — Etapas 8 y 9: alarmas de las tareas periódicas (SPECS §13.1).
-- AL12 (retención > 30 min) y AL13 (permanencia > 2 h) se generan una sola vez
-- por objeto vigilado aunque la web se reinicie: la clave es el id de la
-- retención (AL12) o «contenedor|ingreso_en» (AL13, un reingreso vuelve a
-- vigilarse). La alarma misma se deduplica por código y origen (§13.4 [DEC]).
-- Idempotente (CREATE TABLE IF NOT EXISTS) para correr en cada arranque (BD-2).

CREATE TABLE IF NOT EXISTS alerta_emitida (
    codigo TEXT NOT NULL CHECK (codigo IN ('AL12', 'AL13')),
    clave TEXT NOT NULL,
    alarma_id INTEGER NOT NULL REFERENCES alarma (id),
    ts TEXT NOT NULL,
    PRIMARY KEY (codigo, clave)
);
