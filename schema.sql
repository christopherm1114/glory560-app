-- ============================================================
-- schema.sql — Estructura de la base de datos (PostgreSQL / Supabase)
--
-- Refleja el estado real de la base a septiembre de 2026.
-- Ejecutar PRIMERO este archivo en el editor SQL de Supabase, y
-- después seed.sql.
--
-- IMPORTANTE: para una base que YA existe, no ejecutes este archivo.
-- Usa migrations/001_alinear_esquema.sql, que aplica solo lo que falta.
-- ============================================================

-- ---------- CATÁLOGOS (datos del manual, solo lectura para usuarios) ----------

CREATE TABLE variantes (
    id                      SMALLINT PRIMARY KEY,
    nombre                  VARCHAR(20)  NOT NULL,   -- ej. "SFG15T CVT"
    motor                   VARCHAR(20)  NOT NULL,   -- 1.8 Aspirado / 1.5 Turbo
    transmision             VARCHAR(10)  NOT NULL,   -- 5MT / 6MT / CVT
    aceite_motor            VARCHAR(20)  DEFAULT 'SM 5W-30',
    capacidad_aceite_l      NUMERIC(3,1),
    bujia_tipo              VARCHAR(40),
    liquido_transmision     VARCHAR(30),
    capacidad_transmision_l NUMERIC(4,2),
    refrigerante_l          NUMERIC(3,1),
    medida_llanta           VARCHAR(20),
    presion_llantas         VARCHAR(40)
);

CREATE TABLE tipos_mantenimiento (
    id           SMALLINT PRIMARY KEY,
    nombre       VARCHAR(60) NOT NULL,
    categoria    VARCHAR(20),                -- Motor / Chasis / Transmisión / A/C / Eléctrico
    descripcion  TEXT,
    -- 'reemplazo' -> aparece en el semáforo de próximos mantenimientos, con precio.
    -- 'inspeccion' -> aparece en la pestaña Recomendaciones, sin precio.
    clase        VARCHAR(15) DEFAULT 'reemplazo',
    -- Referencia de precio de mercado en Guayaquil, mostrada en la ficha del control.
    mercado_min  NUMERIC(10,2),
    mercado_max  NUMERIC(10,2),
    mercado_nota TEXT
);

CREATE TABLE intervalos (
    id                    INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    variante_id           SMALLINT NOT NULL REFERENCES variantes(id),
    tipo_mantenimiento_id SMALLINT NOT NULL REFERENCES tipos_mantenimiento(id),
    intervalo_km          INT,
    intervalo_meses       SMALLINT,
    insumo                VARCHAR(60),
    cantidad              NUMERIC(5,2),
    -- Un solo intervalo por combinación variante + control. Sin esta
    -- restricción, volver a ejecutar seed.sql duplica todas las filas.
    CONSTRAINT intervalos_variante_tipo_key UNIQUE (variante_id, tipo_mantenimiento_id)
);

-- ---------- DATOS DE LAS PERSONAS ----------

CREATE TABLE usuarios (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    telegram_id    BIGINT       UNIQUE NOT NULL,
    telefono       VARCHAR(20)  UNIQUE NOT NULL,
    nombre         VARCHAR(120) NOT NULL,
    estado         VARCHAR(15)  NOT NULL DEFAULT 'pendiente',  -- pendiente / aprobado / rechazado
    rol            VARCHAR(10)  NOT NULL DEFAULT 'usuario',    -- usuario / admin
    fecha_registro TIMESTAMPTZ  DEFAULT now(),
    -- Contraseña heredada en texto plano (= el teléfono). PENDIENTE DE ELIMINAR
    -- una vez que todos los usuarios tengan clave_hash. Ver migrations/.
    clave          VARCHAR(120),
    -- Contraseña cifrada: 'pbkdf2_sha256$iteraciones$sal$hash'.
    clave_hash     VARCHAR(200),
    -- Recuperación de contraseña por Telegram: código de 6 dígitos y su vencimiento.
    reset_codigo   VARCHAR(10),
    reset_expira   TIMESTAMPTZ
);

CREATE TABLE vehiculos (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id             BIGINT   NOT NULL REFERENCES usuarios(id),
    variante_id            SMALLINT NOT NULL REFERENCES variantes(id),
    placa                  VARCHAR(12) NOT NULL,
    anio_modelo            SMALLINT,
    kilometraje_actual     INT  DEFAULT 0,
    fecha_actualizacion_km DATE,
    fecha_ultimo_aceite    DATE
);

CREATE TABLE mantenimientos (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vehiculo_id           BIGINT   NOT NULL REFERENCES vehiculos(id),
    tipo_mantenimiento_id SMALLINT NOT NULL REFERENCES tipos_mantenimiento(id),
    fecha                 DATE NOT NULL,       -- fecha en que se hizo el servicio
    kilometraje           INT  NOT NULL,
    costo                 NUMERIC(10,2),
    taller                VARCHAR(80),
    notas                 TEXT,
    creado_en             TIMESTAMPTZ DEFAULT now()   -- cuándo se registró en el sistema
);

CREATE TABLE alertas (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vehiculo_id           BIGINT   NOT NULL REFERENCES vehiculos(id),
    tipo_mantenimiento_id SMALLINT NOT NULL REFERENCES tipos_mantenimiento(id),
    fecha_programada      DATE,
    fecha_enviada         TIMESTAMPTZ,
    estado                VARCHAR(15) DEFAULT 'pendiente'  -- pendiente / enviada / atendida
);

-- Historial de lecturas del odómetro. Alimenta el gráfico de kilometraje
-- del panel. Se escribe en cada /km, en cada edición de perfil y al
-- registrar un mantenimiento con kilometraje mayor al conocido.
CREATE TABLE lecturas_km (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vehiculo_id BIGINT NOT NULL REFERENCES vehiculos(id),
    kilometraje INT    NOT NULL,
    fecha       DATE   NOT NULL
);

-- ---------- ESTADO DE CONVERSACIÓN DEL BOT ----------
-- Como el registro tiene varias preguntas, necesitamos recordar en qué paso
-- va cada usuario y guardar las respuestas parciales. Esta tabla hace eso.
CREATE TABLE estado_conversacion (
    telegram_id BIGINT PRIMARY KEY,
    paso        VARCHAR(40),
    datos       JSONB DEFAULT '{}'::jsonb,
    actualizado TIMESTAMPTZ DEFAULT now()
);

-- ---------- ÍNDICES ----------
-- Sostienen las consultas que la aplicación ejecuta con más frecuencia.

-- db.ultimo_mantenimiento(): el servicio más reciente por km, de un tipo.
CREATE INDEX idx_mant_vehiculo_tipo_km
    ON mantenimientos (vehiculo_id, tipo_mantenimiento_id, kilometraje DESC);

-- db.historial(): historial del vehículo ordenado por fecha.
CREATE INDEX idx_mant_vehiculo_fecha
    ON mantenimientos (vehiculo_id, fecha DESC, id DESC);

-- db.historial_km(): serie del gráfico de kilometraje.
CREATE INDEX idx_lecturas_vehiculo_fecha
    ON lecturas_km (vehiculo_id, fecha);

-- db.buscar_vehiculo_de_usuario(): se llama en casi todas las rutas.
CREATE INDEX idx_vehiculos_usuario
    ON vehiculos (usuario_id);

-- db.listar_usuarios_pendientes() y listar_usuarios_aprobados().
CREATE INDEX idx_usuarios_estado
    ON usuarios (estado);

-- db.alerta_reciente_existe(): control anti-spam de recordatorios.
CREATE INDEX idx_alertas_vehiculo_tipo_enviada
    ON alertas (vehiculo_id, tipo_mantenimiento_id, fecha_enviada DESC);
