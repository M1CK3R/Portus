-- esquema.sql PORTUS — regenerado a partir de db/migraciones/ (CODESTYLE BD-2).
-- NO editar a mano: se regenera con scripts/regenerar_esquema.py.
-- Migraciones incluidas: 001_tablas_del_puente.sql, 002_tablas_web.sql,
--   003_tablas_del_turno.sql, 004_tablas_de_etapa6.sql

-- ============================================================================
-- 001_tablas_del_puente.sql
-- ============================================================================
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

-- ============================================================================
-- 002_tablas_web.sql
-- ============================================================================
-- 002_tablas_web.sql — Etapa 4: núcleo de la aplicación web (SPECS §7, §17, §18).
-- Tablas mínimas del núcleo: usuarios y roles (§7.1–7.2), manifiesto con los
-- dueños para los filtros de propiedad (§7.4, §7.5.2), código de vinculación
-- de transportista (§15.1, A17) y auditoría de intentos rechazados (§7.5.5).
-- Las tablas de turnos, citas, retenciones y grúa llegan con su etapa (BD-2).

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

-- ============================================================================
-- 003_tablas_del_turno.sql
-- ============================================================================
-- 003_tablas_del_turno.sql — Etapa 5: lógica del turno en el servidor
-- (SPECS §8 máquina de estados, §9.4 garita, §10 retenciones, §11 citas,
--  §12 patio/trabajos, §13 alarmas, §17.1 modelo de datos).
-- La semilla de plazas 1–3 (§10.1) vive aquí porque es estructura del
-- sistema; los catálogos (contenedores, vehículos, posiciones del patio)
-- son datos de instalación y van en herramientas/crear_datos_semilla.py.

-- ---------------------------------------------------------------------------
-- Catálogos que la validación de garita consulta (§9.4).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS vehiculo (
    id INTEGER PRIMARY KEY,
    -- Identificador que la garita lee (tarjeta/etiqueta) y que viaja en GAR.veh.
    identificador TEXT NOT NULL UNIQUE,
    transportista_id INTEGER NOT NULL REFERENCES usuario (id),
    -- Tara del camión vacío en gramos; base de la fórmula de pesaje (A4 [DEC]).
    tara_g INTEGER NOT NULL DEFAULT 0 CHECK (tara_g >= 0)
);

CREATE INDEX IF NOT EXISTS ix_vehiculo_transportista ON vehiculo (transportista_id);
-- Justificación: el manifiesto vigente se busca por el transportista del
-- vehículo presentado en garita (§9.4, paso 2).

CREATE TABLE IF NOT EXISTS solicitud_levante (
    id INTEGER PRIMARY KEY,
    manifiesto_id INTEGER NOT NULL REFERENCES manifiesto (id),
    agente_id INTEGER REFERENCES usuario (id),
    autoridad_id INTEGER REFERENCES usuario (id),
    -- Estados del ciclo del levante que la garita consulta (§8.3, §9.4).
    estado TEXT NOT NULL DEFAULT 'sin_solicitud' CHECK (
        estado IN ('sin_solicitud', 'solicitada', 'otorgada', 'retenida')
    ),
    canal TEXT CHECK (canal IN ('verde', 'rojo')),
    motivo TEXT,
    solicitada_en TEXT,
    resuelta_en TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_levante_por_manifiesto
    ON solicitud_levante (manifiesto_id);
-- Justificación: un manifiesto tiene a lo sumo un levante vigente; la
-- validación de garita lo consulta por manifiesto_id (§9.4, paso 3).

-- ---------------------------------------------------------------------------
-- Agenda: franjas de 15 min con capacidad 2 (§11.1) y citas.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS franja (
    fecha TEXT NOT NULL,
    inicio TEXT NOT NULL,
    fin TEXT NOT NULL,
    capacidad INTEGER NOT NULL DEFAULT 2 CHECK (capacidad = 2),
    bloqueada INTEGER NOT NULL DEFAULT 0 CHECK (bloqueada IN (0, 1)),
    PRIMARY KEY (fecha, inicio)
);

CREATE TABLE IF NOT EXISTS cita (
    id INTEGER PRIMARY KEY,
    manifiesto_id INTEGER NOT NULL REFERENCES manifiesto (id),
    transportista_id INTEGER NOT NULL REFERENCES usuario (id),
    franja_fecha TEXT NOT NULL,
    franja_inicio TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'programada' CHECK (
        estado IN ('programada', 'cumplida', 'vencida', 'cancelada')
    ),
    -- A11 [DEC]: la marca de ventana se fija al autorizar el ingreso y el
    -- estado final depende del desenlace del turno (cumplida al cerrar).
    cumplida_en_ventana INTEGER CHECK (cumplida_en_ventana IN (0, 1)),
    creada_en TEXT NOT NULL,
    -- La franja tiene PK compuesta (fecha, inicio); la referencia también.
    FOREIGN KEY (franja_fecha, franja_inicio) REFERENCES franja (fecha, inicio)
);

CREATE INDEX IF NOT EXISTS ix_cita_manifiesto ON cita (manifiesto_id);
-- Justificación: la garita busca la cita programada del manifiesto (§9.4).

-- Como máximo una cita programada por manifiesto (§17.3: por contenedor).
CREATE UNIQUE INDEX IF NOT EXISTS ix_cita_programada_por_manifiesto
    ON cita (manifiesto_id) WHERE estado = 'programada';

-- ---------------------------------------------------------------------------
-- Turno, intentos de ingreso, pesajes y línea de tiempo (§8, §9.4).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS turno (
    id INTEGER PRIMARY KEY,
    vehiculo_id INTEGER NOT NULL REFERENCES vehiculo (id),
    manifiesto_id INTEGER NOT NULL REFERENCES manifiesto (id),
    cita_id INTEGER REFERENCES cita (id),
    tipo_op TEXT NOT NULL CHECK (tipo_op IN ('DEPOSITO', 'RETIRO')),
    -- Los 10 estados exactos del SPECS §8.1; «Programado» queda fuera del
    -- ciclo normal (A1 [DEC]: el turno nace en EnGarita al autorizar).
    estado TEXT NOT NULL CHECK (
        estado IN (
            'Programado', 'EnGarita', 'EnPesajeEntrada', 'EnRuta',
            'EnTransferencia', 'EnPesajeSalida', 'EnSalida', 'Retenido',
            'Cerrado', 'Anulado'
        )
    ),
    -- A2: estado guardado al retener; el regreso lo mapea estado_de_regreso().
    estado_previo_retencion TEXT,
    posicion_patio TEXT,
    nivel INTEGER CHECK (nivel IN (1, 2)),
    peso_entrada_g INTEGER,
    peso_salida_g INTEGER,
    -- Riesgo de retención al autorizar: canal rojo o llegada fuera de ventana.
    canal TEXT CHECK (canal IN ('verde', 'rojo')),
    dentro_de_ventana INTEGER CHECK (dentro_de_ventana IN (0, 1)),
    creado_en TEXT NOT NULL,
    cerrado_en TEXT,
    motivo_anulacion TEXT
);

CREATE INDEX IF NOT EXISTS ix_turno_estado ON turno (estado);
-- Justificación: los listados de la pestaña Turnos separan activos e
-- históricos por estado (§14.2) y la salida busca el turno en EnSalida (§8.6).

CREATE INDEX IF NOT EXISTS ix_turno_vehiculo ON turno (vehiculo_id);
-- Justificación: GAR/PES/SAL llegan por identificador de vehículo; los
-- servicios localizan el turno activo de ese vehículo en cada evento.

CREATE TABLE IF NOT EXISTS intento_ingreso (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    -- Un rechazo no crea turno pero sí registra el intento (§8.2 regla 1).
    -- vehiculo_id es NULL cuando el identificador ni siquiera está registrado.
    identificador TEXT NOT NULL,
    vehiculo_id INTEGER REFERENCES vehiculo (id),
    causa TEXT NOT NULL CHECK (
        causa IN (
            'VEHICULO_DESCONOCIDO', 'SIN_MANIFIESTO', 'SIN_LEVANTE',
            'LEVANTE_RETENIDO', 'SIN_CITA', 'PARQUEO_LLENO'
        )
    ),
    detalle TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_intento_ts ON intento_ingreso (ts);
-- Justificación: la revisión de intentos rechazados se lee en orden temporal
-- (mismo patrón que auditoria_rechazo de la Etapa 4).

CREATE TABLE IF NOT EXISTS pesaje (
    id INTEGER PRIMARY KEY,
    turno_id INTEGER NOT NULL REFERENCES turno (id),
    momento TEXT NOT NULL CHECK (momento IN ('entrada', 'salida')),
    peso_g INTEGER NOT NULL CHECK (peso_g >= 0),
    muestras INTEGER NOT NULL DEFAULT 0,
    meseta INTEGER NOT NULL DEFAULT 1 CHECK (meseta IN (0, 1)),
    dentro_tolerancia INTEGER NOT NULL CHECK (dentro_tolerancia IN (0, 1)),
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_pesaje_turno ON pesaje (turno_id);
-- Justificación: la evidencia de peso de una retención (§10.4) y la línea
-- de tiempo consultan los pesajes del turno.

CREATE TABLE IF NOT EXISTS evento_turno (
    -- Línea de tiempo del turno (§14.2): segundo, origen, descripción, valores.
    id INTEGER PRIMARY KEY,
    turno_id INTEGER NOT NULL REFERENCES turno (id),
    ts TEXT NOT NULL,
    origen TEXT NOT NULL,
    tipo TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    valores TEXT NOT NULL DEFAULT '{}',
    seq INTEGER
);

CREATE INDEX IF NOT EXISTS ix_evento_turno ON evento_turno (turno_id, id);
-- Justificación: el detalle del turno muestra su línea de tiempo completa en
-- orden (§14.2); la consulta siempre filtra por turno_id.

-- ---------------------------------------------------------------------------
-- Retenciones y parqueo de 3 plazas (§10).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS plaza_parqueo (
    numero INTEGER PRIMARY KEY CHECK (numero BETWEEN 1 AND 3),
    turno_id INTEGER REFERENCES turno (id),
    ocupada_desde TEXT
);

-- Semilla estructural del parqueo (§10.1: plazas 1–3 administradas en lógico).
-- Idempotente: db/esquema.sql se ejecuta en cada arranque del puente (BD-2),
-- y la fila ya existente con su turno asignado no debe tocarse.
INSERT OR IGNORE INTO plaza_parqueo (numero, turno_id, ocupada_desde)
    VALUES (1, NULL, NULL), (2, NULL, NULL), (3, NULL, NULL);

CREATE TABLE IF NOT EXISTS retencion (
    id INTEGER PRIMARY KEY,
    turno_id INTEGER NOT NULL REFERENCES turno (id),
    causa TEXT NOT NULL CHECK (causa IN ('RT01', 'RT02', 'RT03', 'RT04', 'RT05', 'RT06')),
    estacion TEXT NOT NULL,
    -- NULL cuando el vehículo queda detenido en su punto sin ramal (A3 [DEC]).
    plaza INTEGER REFERENCES plaza_parqueo (numero),
    estado TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'resuelta')),
    peso_declarado_g INTEGER,
    peso_medido_g INTEGER,
    resolucion TEXT CHECK (resolucion IN ('ACLARAR', 'CORREGIR', 'RECHAZAR')),
    motivo TEXT,
    observacion TEXT,
    resuelta_por INTEGER REFERENCES usuario (id),
    creada_en TEXT NOT NULL,
    resuelta_en TEXT
);

CREATE INDEX IF NOT EXISTS ix_retencion_estado ON retencion (estado);
-- Justificación: la bandeja separa abiertas y resueltas (§14.3) y la
-- asignación de plazas consulta retenciones abiertas del turno.

-- ---------------------------------------------------------------------------
-- Patio, inventario y trabajos de grúa (§12).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS posicion_patio (
    id TEXT PRIMARY KEY,
    estado TEXT NOT NULL DEFAULT 'libre' CHECK (
        estado IN ('libre', 'reservada', 'ocupada', 'bloqueada')
    )
);

CREATE TABLE IF NOT EXISTS inventario (
    contenedor_id TEXT PRIMARY KEY REFERENCES contenedor (id),
    posicion TEXT NOT NULL REFERENCES posicion_patio (id),
    nivel INTEGER NOT NULL CHECK (nivel IN (1, 2)),
    ingreso_en TEXT NOT NULL,
    remociones INTEGER NOT NULL DEFAULT 0 CHECK (remociones >= 0),
    autorizacion TEXT NOT NULL DEFAULT 'SIN_LEVANTE'
);

-- Un solo contenedor por celda (posición, nivel) del patio lineal (§12.1).
CREATE UNIQUE INDEX IF NOT EXISTS ix_inventario_ubicacion
    ON inventario (posicion, nivel);

CREATE TABLE IF NOT EXISTS trabajo_grua (
    id INTEGER PRIMARY KEY,
    turno_id INTEGER NOT NULL REFERENCES turno (id),
    tipo TEXT NOT NULL CHECK (tipo IN ('DEPOSITO', 'RETIRO', 'REMOCION')),
    contenedor_id TEXT NOT NULL,
    origen TEXT NOT NULL,
    destino TEXT NOT NULL,
    nivel INTEGER NOT NULL CHECK (nivel IN (1, 2)),
    estado TEXT NOT NULL DEFAULT 'PENDIENTE' CHECK (
        estado IN ('PENDIENTE', 'EN_CURSO', 'COMPLETADO', 'ABORTADO')
    ),
    orden INTEGER NOT NULL,
    creado_en TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_trabajo_turno ON trabajo_grua (turno_id, orden);
-- Justificación: el retiro no inicia hasta completar las remociones (§12.5);
-- el orden dentro del turno se consulta siempre junto con el turno.

-- ---------------------------------------------------------------------------
-- Alarmas del servidor, historial del manifiesto, notificaciones y
-- deduplicación del consumidor (§13, §10.3, §15.3, §5.5).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS alarma (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL CHECK (codigo IN (
        'AL01', 'AL02', 'AL03', 'AL04', 'AL05', 'AL06', 'AL07', 'AL08',
        'AL09', 'AL10', 'AL11', 'AL12', 'AL13', 'AL14'
    )),
    severidad TEXT NOT NULL CHECK (severidad IN ('CRITICA', 'ALTA', 'MEDIA', 'BAJA')),
    origen TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    datos TEXT NOT NULL DEFAULT '{}',
    -- §13.4 [DEC]: repetición de la misma condición incrementa el contador
    -- en lugar de crear otra fila activa.
    repeticiones INTEGER NOT NULL DEFAULT 1 CHECK (repeticiones >= 1),
    estado TEXT NOT NULL DEFAULT 'activa' CHECK (estado IN ('activa', 'reconocida')),
    ts TEXT NOT NULL,
    reconocida_por INTEGER REFERENCES usuario (id),
    reconocida_ts TEXT,
    comentario TEXT
);

CREATE INDEX IF NOT EXISTS ix_alarma_estado ON alarma (estado);
-- Justificación: la lista de activas (§13.3) filtra por estado; el dedup de
-- §13.4 consulta si ya existe una activa del mismo código y origen.

CREATE TABLE IF NOT EXISTS manifiesto_historial (
    id INTEGER PRIMARY KEY,
    manifiesto_id INTEGER NOT NULL REFERENCES manifiesto (id),
    campo TEXT NOT NULL,
    valor_anterior TEXT NOT NULL,
    valor_nuevo TEXT NOT NULL,
    motivo TEXT,
    retencion_id INTEGER REFERENCES retencion (id),
    usuario_id INTEGER REFERENCES usuario (id),
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_historial_manifiesto ON manifiesto_historial (manifiesto_id);
-- Justificación: Corregir guarda el peso anterior (§10.3) y el detalle del
-- manifiesto muestra su historial (§18: /manifiestos/{id}/historial).

CREATE TABLE IF NOT EXISTS notificacion (
    id INTEGER PRIMARY KEY,
    transportista_id INTEGER NOT NULL REFERENCES usuario (id),
    tipo TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    ts TEXT NOT NULL,
    entregado INTEGER NOT NULL DEFAULT 0 CHECK (entregado IN (0, 1))
);

CREATE INDEX IF NOT EXISTS ix_notificacion_entrega ON notificacion (entregado, transportista_id);
-- Justificación: el bot (Etapa 10) despacha las pendientes de un
-- transportista vinculado (§15.3) consultando por ese índice.

CREATE TABLE IF NOT EXISTS evento_procesado (
    -- Deduplicación por id del consumidor de la lógica (§5.5, P-4): los
    -- eventos reenviados tras SYN conservan el id y no se vuelven a aplicar.
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Manifiesto: se recrea con los catálogos finales de estados (§8.3). SQLite
-- no altera CHECK: copia con mapeo, DROP y RENAME (BD-2).
-- Idempotente: descarta un manifiesto_etapa5 huérfano de una corrida
-- interrumpida (Ctrl+C entre CREATE y RENAME) antes de recrear.
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS manifiesto_etapa5;

CREATE TABLE manifiesto_etapa5 (
    id INTEGER PRIMARY KEY,
    contenedor_id TEXT NOT NULL REFERENCES contenedor (id),
    naviera_id INTEGER NOT NULL REFERENCES usuario (id),
    transportista_id INTEGER NOT NULL REFERENCES usuario (id),
    tipo_op TEXT NOT NULL CHECK (tipo_op IN ('DEPOSITO', 'RETIRO')),
    peso_declarado_g INTEGER NOT NULL CHECK (peso_declarado_g > 0),
    tolerancia_pct INTEGER NOT NULL DEFAULT 5 CHECK (tolerancia_pct BETWEEN 1 AND 100),
    -- Estados documentales y operativos exactos del SPECS §8.3.
    estado_documental TEXT NOT NULL DEFAULT 'declarado' CHECK (
        estado_documental IN (
            'declarado', 'declaracion_presentada', 'levante_solicitado',
            'levante_otorgado', 'levante_retenido', 'anulado'
        )
    ),
    estado_operativo TEXT NOT NULL DEFAULT 'sin_turno' CHECK (
        estado_operativo IN ('sin_turno', 'en_curso', 'completado', 'anulado')
    ),
    observaciones TEXT NOT NULL DEFAULT '',
    creado_en TEXT NOT NULL,
    anulado_en TEXT
);

INSERT INTO manifiesto_etapa5 (
    id, contenedor_id, naviera_id, transportista_id, tipo_op, peso_declarado_g,
    tolerancia_pct, estado_documental, estado_operativo, observaciones, creado_en, anulado_en
)
SELECT
    id, contenedor_id, naviera_id, transportista_id, tipo_op, peso_declarado_g,
    tolerancia_pct,
    CASE estado_documental
        WHEN 'SIN_DECLARACION' THEN 'declarado'
        WHEN 'DECLARACION_PRESENTADA' THEN 'declaracion_presentada'
        WHEN 'LEVANTE_SOLICITADO' THEN 'levante_solicitado'
        WHEN 'LEVANTE_OTORGADO' THEN 'levante_otorgado'
        WHEN 'LEVANTE_RETENIDO' THEN 'levante_retenido'
        WHEN 'ANULADO' THEN 'anulado'
        ELSE estado_documental
    END,
    CASE estado_operativo
        WHEN 'PENDIENTE' THEN 'sin_turno'
        WHEN 'EN_CURSO' THEN 'en_curso'
        WHEN 'COMPLETADO' THEN 'completado'
        WHEN 'ANULADO' THEN 'anulado'
        ELSE estado_operativo
    END,
    observaciones, creado_en, anulado_en
FROM manifiesto;

DROP TABLE manifiesto;
ALTER TABLE manifiesto_etapa5 RENAME TO manifiesto;

-- Un solo manifiesto pendiente por contenedor (SPECS §17.3), con el catálogo nuevo.
CREATE UNIQUE INDEX IF NOT EXISTS ix_manifiesto_pendiente_por_contenedor
    ON manifiesto (contenedor_id) WHERE estado_operativo = 'sin_turno';

CREATE INDEX IF NOT EXISTS ix_manifiesto_naviera ON manifiesto (naviera_id);
-- Justificación: el filtro de propiedad de NAVIERA (§7.5.2) consulta por su id.
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
