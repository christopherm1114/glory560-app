-- ============================================================
-- schema.sql — Estructura de la base de datos (PostgreSQL / Supabase)
-- Ejecuta este archivo PRIMERO en el editor SQL de Supabase.
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
    id          SMALLINT PRIMARY KEY,
    nombre      VARCHAR(60) NOT NULL,
    categoria   VARCHAR(20),               -- Motor / Chasis / Transmisión / A/C / Eléctrico
    descripcion TEXT
);

CREATE TABLE intervalos (
    id                    INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    variante_id           SMALLINT NOT NULL REFERENCES variantes(id),
    tipo_mantenimiento_id SMALLINT NOT NULL REFERENCES tipos_mantenimiento(id),
    intervalo_km          INT,
    intervalo_meses       SMALLINT,
    insumo                VARCHAR(60),
    cantidad              NUMERIC(5,2),
    UNIQUE (variante_id, tipo_mantenimiento_id)
);

-- ---------- DATOS DE LAS PERSONAS ----------

CREATE TABLE usuarios (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    telegram_id    BIGINT      UNIQUE NOT NULL,
    telefono       VARCHAR(20) UNIQUE NOT NULL,
    nombre         VARCHAR(120) NOT NULL,
    estado         VARCHAR(15)  NOT NULL DEFAULT 'pendiente',  -- pendiente / aprobado / rechazado
    rol            VARCHAR(10)  NOT NULL DEFAULT 'usuario',     -- usuario / admin
    fecha_registro TIMESTAMPTZ  DEFAULT now()
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
    fecha                 DATE NOT NULL,
    kilometraje           INT  NOT NULL,
    costo                 NUMERIC(10,2),
    taller                VARCHAR(80),
    notas                 TEXT
);

CREATE TABLE alertas (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vehiculo_id           BIGINT   NOT NULL REFERENCES vehiculos(id),
    tipo_mantenimiento_id SMALLINT NOT NULL REFERENCES tipos_mantenimiento(id),
    fecha_programada      DATE,
    fecha_enviada         TIMESTAMPTZ,
    estado                VARCHAR(15) DEFAULT 'pendiente'  -- pendiente / enviada / atendida
);

-- ---------- ESTADO DE CONVERSACIÓN DEL BOT ----------
-- Como el registro tiene varias preguntas, necesitamos recordar en qué paso
-- va cada usuario y guardar las respuestas parciales. Esta tabla hace eso.
-- Usamos JSONB para guardar las respuestas que se van acumulando.
CREATE TABLE estado_conversacion (
    telegram_id BIGINT PRIMARY KEY,
    paso        VARCHAR(40),
    datos       JSONB DEFAULT '{}'::jsonb,
    actualizado TIMESTAMPTZ DEFAULT now()
);
