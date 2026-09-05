-- ============================================================
-- 001_alinear_esquema.sql
--
-- Alinea una base YA EXISTENTE con lo que declara schema.sql.
-- Pensado para la base de producción, que fue creciendo a mano
-- desde el editor de Supabase sin dejar registro de los cambios.
--
-- Es IDEMPOTENTE: se puede ejecutar varias veces sin efecto adicional.
-- No borra datos ni columnas.
--
-- CÓMO USARLO
--   Supabase -> SQL Editor -> New query -> pegar todo -> Run.
--   Lee los avisos (NOTICE) que imprime al final.
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. Columnas que el código usa y que pudieran faltar
--    En la base actual ya existen todas; los ADD COLUMN IF NOT
--    EXISTS quedan aquí para que una base creada desde una
--    versión vieja de schema.sql también se ponga al día.
-- ------------------------------------------------------------

ALTER TABLE tipos_mantenimiento
    ADD COLUMN IF NOT EXISTS clase        VARCHAR(15) DEFAULT 'reemplazo',
    ADD COLUMN IF NOT EXISTS mercado_min  NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS mercado_max  NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS mercado_nota TEXT;

ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS clave        VARCHAR(120),
    ADD COLUMN IF NOT EXISTS clave_hash   VARCHAR(200),
    ADD COLUMN IF NOT EXISTS reset_codigo VARCHAR(10),
    ADD COLUMN IF NOT EXISTS reset_expira TIMESTAMPTZ;

ALTER TABLE mantenimientos
    ADD COLUMN IF NOT EXISTS creado_en TIMESTAMPTZ DEFAULT now();

CREATE TABLE IF NOT EXISTS lecturas_km (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vehiculo_id BIGINT NOT NULL REFERENCES vehiculos(id),
    kilometraje INT    NOT NULL,
    fecha       DATE   NOT NULL
);

-- ------------------------------------------------------------
-- 2. Restricción única perdida en 'intervalos'
--
--    El schema.sql original declaraba UNIQUE (variante_id,
--    tipo_mantenimiento_id), pero la base de producción no la
--    tiene. Sin ella, volver a ejecutar seed.sql duplica los 40
--    intervalos en silencio y el motor de cálculo empieza a
--    evaluar el mismo control dos veces.
--
--    Si ya hay duplicados, el ALTER falla. En ese caso, ejecuta
--    primero la consulta de diagnóstico del final de este archivo.
-- ------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.intervalos'::regclass
          AND conname  = 'intervalos_variante_tipo_key'
    ) THEN
        ALTER TABLE intervalos
            ADD CONSTRAINT intervalos_variante_tipo_key
            UNIQUE (variante_id, tipo_mantenimiento_id);
        RAISE NOTICE 'Restriccion UNIQUE agregada a intervalos.';
    ELSE
        RAISE NOTICE 'La restriccion UNIQUE de intervalos ya existia.';
    END IF;
END $$;

-- ------------------------------------------------------------
-- 3. Índices de las consultas más frecuentes
-- ------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_mant_vehiculo_tipo_km
    ON mantenimientos (vehiculo_id, tipo_mantenimiento_id, kilometraje DESC);

CREATE INDEX IF NOT EXISTS idx_mant_vehiculo_fecha
    ON mantenimientos (vehiculo_id, fecha DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_lecturas_vehiculo_fecha
    ON lecturas_km (vehiculo_id, fecha);

CREATE INDEX IF NOT EXISTS idx_vehiculos_usuario
    ON vehiculos (usuario_id);

CREATE INDEX IF NOT EXISTS idx_usuarios_estado
    ON usuarios (estado);

CREATE INDEX IF NOT EXISTS idx_alertas_vehiculo_tipo_enviada
    ON alertas (vehiculo_id, tipo_mantenimiento_id, fecha_enviada DESC);

COMMIT;


-- ============================================================
-- DIAGNÓSTICO (opcional, solo lectura)
-- Ejecuta estas consultas por separado si algo falló arriba.
-- ============================================================

-- ¿Hay intervalos duplicados que impidan crear la restricción única?
-- Si devuelve filas, hay que borrar los sobrantes antes de reintentar.
--
--   SELECT variante_id, tipo_mantenimiento_id, count(*) AS repeticiones,
--          array_agg(id ORDER BY id) AS ids
--   FROM intervalos
--   GROUP BY variante_id, tipo_mantenimiento_id
--   HAVING count(*) > 1;

-- ¿Cuántos controles están marcados como inspección?
-- Si devuelve 0, la pestaña "Recomendaciones" del panel sale vacía
-- aunque el esquema esté correcto: es un asunto de datos, no de estructura.
--
--   SELECT clase, count(*) FROM tipos_mantenimiento GROUP BY clase;

-- ¿Qué usuarios siguen con la contraseña heredada (el teléfono en claro)?
-- Mientras clave_hash sea NULL, esa cuenta se abre conociendo el teléfono.
--
--   SELECT id, nombre, estado, rol
--   FROM usuarios
--   WHERE clave_hash IS NULL
--   ORDER BY id;
