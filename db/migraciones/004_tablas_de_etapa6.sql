-- 004_tablas_de_etapa6.sql — Etapa 6: interfaz del rol TERMINAL (SPECS §14).
-- Ciclo de grúa registrado (§12.6: ts_inicio, ts_fin, tipo, distancia_traslacion,
-- resultado, turno_id) y reporte de corrida (§16.3 [PROP]: etiqueta, rango,
-- política activa, resultado en JSON, quién lo generó).
-- Todo con CREATE TABLE IF NOT EXISTS para ser idempotente en cada arranque (BD-2).

CREATE TABLE IF NOT EXISTS ciclo_grua (
    id INTEGER PRIMARY KEY,
    turno_id INTEGER NOT NULL REFERENCES turno (id),
    trabajo_id INTEGER REFERENCES trabajo_grua (id),
    -- tipo replica trabajo_grua.tipo para el histórico aun si el trabajo se borra.
    tipo TEXT NOT NULL CHECK (tipo IN ('DEPOSITO', 'RETIRO', 'REMOCION')),
    ts_inicio TEXT NOT NULL,
    ts_fin TEXT NOT NULL,
    -- Distancia de traslación en unidades de la maqueta (cm); 0 si no se reporta.
    distancia_traslacion INTEGER NOT NULL DEFAULT 0 CHECK (distancia_traslacion >= 0),
    resultado TEXT NOT NULL CHECK (resultado IN ('COMPLETADO', 'ABORTADO')),
    creado_en TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_ciclo_grua_turno ON ciclo_grua (turno_id);
-- Justificación: las métricas 1-3 de §16.1 agrupan ciclos por turno cerrado.

CREATE INDEX IF NOT EXISTS ix_ciclo_grua_ts ON ciclo_grua (ts_inicio);
-- Justificación: el reporte acota por rango temporal (§16.3) y la gráfica de
-- ciclos muestra los últimos N ordenados por ts_inicio (§12.6).

CREATE TABLE IF NOT EXISTS reporte (
    id INTEGER PRIMARY KEY,
    etiqueta TEXT NOT NULL,
    inicio TEXT NOT NULL,
    fin TEXT NOT NULL,
    -- Política de asignación activa al generar (§12.4, §16.3): FASE1 hoy.
    politica TEXT NOT NULL DEFAULT 'FASE1',
    -- Las 8 métricas de §16.1 en JSON para recuperar y comparar (§16.3 [PROP]).
    resultado TEXT NOT NULL,
    generado_por INTEGER REFERENCES usuario (id),
    generado_en TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_reporte_ts ON reporte (generado_en);
-- Justificación: la pestaña Reportes lista los generados ordenados por fecha.
