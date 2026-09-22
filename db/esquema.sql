-- esquema.sql PORTUS — regenerado a partir de db/migraciones/ (CODESTYLE BD-2).
-- Contenido actual: migración 001_tablas_del_puente.sql (Etapa 3)
-- + migración 002_tablas_web.sql (Etapa 4: núcleo de la web).

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

-- --- 002_tablas_web.sql ---

CREATE TABLE IF NOT EXISTS usuario (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    -- Rol ∈ los 5 exactos del SPECS §7.1; ningún otro.
    rol TEXT NOT NULL CHECK (
        rol IN ('TERMINAL', 'NAVIERA', 'AGENTE', 'AUTORIDAD', 'TRANSPORTISTA')
    ),
    nombre_mostrado TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contenedor (
    id TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL
);

-- El manifiesto se crea en la Etapa 4 solo como dueño de los filtros de
-- propiedad (§7.4: NAVIERA ve los propios; TRANSPORTISTA su carga). Su ciclo
-- documental completo se implementa en la Etapa 5 (§9), que ajustará los
-- CHECK de los estados con el catálogo final.
CREATE TABLE IF NOT EXISTS manifiesto (
    id INTEGER PRIMARY KEY,
    contenedor_id TEXT NOT NULL REFERENCES contenedor (id),
    naviera_id INTEGER NOT NULL REFERENCES usuario (id),
    transportista_id INTEGER NOT NULL REFERENCES usuario (id),
    tipo_op TEXT NOT NULL CHECK (tipo_op IN ('DEPOSITO', 'RETIRO')),
    peso_declarado_g INTEGER NOT NULL CHECK (peso_declarado_g > 0),
    tolerancia_pct INTEGER NOT NULL DEFAULT 5 CHECK (tolerancia_pct BETWEEN 1 AND 100),
    estado_documental TEXT NOT NULL DEFAULT 'SIN_DECLARACION',
    estado_operativo TEXT NOT NULL DEFAULT 'PENDIENTE',
    observaciones TEXT NOT NULL DEFAULT '',
    creado_en TEXT NOT NULL,
    anulado_en TEXT
);

-- Un solo manifiesto pendiente por contenedor (SPECS §17.3).
CREATE UNIQUE INDEX IF NOT EXISTS ix_manifiesto_pendiente_por_contenedor
    ON manifiesto (contenedor_id) WHERE estado_operativo = 'PENDIENTE';

CREATE INDEX IF NOT EXISTS ix_manifiesto_naviera ON manifiesto (naviera_id);
-- Justificación: el filtro de propiedad de NAVIERA (§7.5.2) consulta por su id.

CREATE TABLE IF NOT EXISTS codigo_vinculacion (
    -- 6 caracteres sin 0/O ni 1/I/L (§15.1 [PROP]); se guarda en claro porque
    -- vive 60 min, es de un solo uso y se invalida al generar uno nuevo.
    codigo TEXT PRIMARY KEY,
    transportista_id INTEGER NOT NULL REFERENCES usuario (id),
    creado_en TEXT NOT NULL,
    expira_en TEXT NOT NULL,
    usado_en TEXT
);

CREATE INDEX IF NOT EXISTS ix_codigo_transportista ON codigo_vinculacion (transportista_id);
-- Justificación: generar un código nuevo invalida los activos previos del
-- mismo transportista (§15.1), operación que consulta por su id.

CREATE TABLE IF NOT EXISTS auditoria_rechazo (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    username TEXT,
    rol TEXT,
    accion TEXT NOT NULL,
    recurso TEXT NOT NULL,
    motivo TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_auditoria_ts ON auditoria_rechazo (ts);
-- Justificación: la demostración de E12/R13 revisa los intentos rechazados
-- (§7.5.5) en orden temporal.
