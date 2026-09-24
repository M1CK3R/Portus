-- 007_canal_de_mensajeria.sql — Etapa 10: bot de Telegram del transportista (SPECS §15, §17.1).
-- Vínculo chat ↔ transportista (§15.4), estado de entrega de cada notificación
-- (§15.4 «entregado y reintentos») y marca del recordatorio de 1 h (§11.5).
-- Las columnas nuevas viven en tablas propias porque el esquema se aplica en
-- cada arranque y SQLite no tiene ALTER TABLE ... ADD COLUMN IF NOT EXISTS.
-- Idempotente (CREATE TABLE IF NOT EXISTS) para correr en cada arranque (BD-2).

CREATE TABLE IF NOT EXISTS vinculo_mensajeria (
    -- Un transportista tiene a lo sumo una cuenta y una cuenta pertenece a un
    -- solo transportista: volver a vincular reemplaza el vínculo anterior.
    transportista_id INTEGER PRIMARY KEY REFERENCES usuario (id),
    -- chat_id de Telegram: entero de hasta 64 bits (§15.4).
    telegram_chat_id INTEGER NOT NULL UNIQUE,
    vinculado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entrega_notificacion (
    -- Reintentos del envío por Telegram. ``notificacion.entregado`` sigue
    -- siendo la marca oficial; aquí queda el historial del intento.
    notificacion_id INTEGER PRIMARY KEY REFERENCES notificacion (id),
    reintentos INTEGER NOT NULL DEFAULT 0 CHECK (reintentos >= 0),
    ultimo_error TEXT,
    entregado_en TEXT
);

CREATE INDEX IF NOT EXISTS ix_notificacion_pendiente_ts ON notificacion (entregado, ts);
-- Justificación: el barrido del bot busca las pendientes posteriores al
-- vínculo del transportista para reenviarlas al volver la conexión (§15.4).

CREATE TABLE IF NOT EXISTS recordatorio_cita (
    -- Un recordatorio por cita y ventana. Reprogramar borra la fila para que
    -- la ventana nueva tenga su propio aviso (§11.4, §11.5).
    cita_id INTEGER PRIMARY KEY REFERENCES cita (id),
    notificacion_id INTEGER NOT NULL REFERENCES notificacion (id),
    ts TEXT NOT NULL
);
