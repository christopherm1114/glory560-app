-- ============================================================
-- 002_rendimiento_consultas.sql
--
-- Hallazgo 6 del informe de auditoría: dos consultas descargan
-- tablas completas y filtran en Python.
--
--   · buscar_usuario_por_telefono_normalizado trae TODA la tabla
--     usuarios en CADA intento de login, incluidos los fallidos.
--     Sin límite de intentos eso era, además, una forma barata de
--     tumbar el servicio. Se arregla con una columna con los nueve
--     últimos dígitos del teléfono, indexada.
--
--   · promedios_por_tipo trae todos los mantenimientos de todos los
--     usuarios en cada carga del panel. Se arregla calculando el
--     promedio en Postgres, que para eso está.
--
-- Es IDEMPOTENTE: se puede ejecutar varias veces sin efecto extra.
-- No borra datos ni columnas.
--
-- CÓMO USARLO
--   Supabase -> SQL Editor -> New query -> pegar todo -> Run.
--
-- La aplicación funciona ANTES y DESPUÉS de ejecutar esto: db.py
-- detecta si la columna y la función existen, y si no, usa el camino
-- antiguo. Así el despliegue y la migración no tienen que coincidir
-- en el tiempo.
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. Teléfono normalizado, indexado
--
--    Se guardan los NUEVE últimos dígitos, que es exactamente lo
--    que compara auth.normalizar_telefono: así '0999123456',
--    '+593 999123456' y '593999123456' caen en el mismo valor.
-- ------------------------------------------------------------

ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS telefono_normalizado VARCHAR(9);

UPDATE usuarios
   SET telefono_normalizado =
       RIGHT(regexp_replace(COALESCE(telefono, ''), '[^0-9]', '', 'g'), 9)
 WHERE telefono_normalizado IS NULL
    OR telefono_normalizado <> RIGHT(regexp_replace(COALESCE(telefono, ''), '[^0-9]', '', 'g'), 9);

CREATE INDEX IF NOT EXISTS idx_usuarios_telefono_norm
    ON usuarios (telefono_normalizado);

-- ------------------------------------------------------------
-- 2. Disparador que mantiene la columna al día
--
--    Se hace en la base y no en la aplicación a propósito: si
--    alguien edita un teléfono desde el editor de Supabase, la
--    columna normalizada tiene que seguirlo igual.
-- ------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_normalizar_telefono()
RETURNS trigger AS $$
BEGIN
    NEW.telefono_normalizado :=
        RIGHT(regexp_replace(COALESCE(NEW.telefono, ''), '[^0-9]', '', 'g'), 9);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tg_normalizar_telefono ON usuarios;
CREATE TRIGGER tg_normalizar_telefono
    BEFORE INSERT OR UPDATE OF telefono ON usuarios
    FOR EACH ROW EXECUTE FUNCTION fn_normalizar_telefono();

-- ------------------------------------------------------------
-- 3. Promedios calculados en Postgres
--
--    Mismas reglas que tenía la versión en Python: se ignoran los
--    costos nulos, los no positivos y los exageradamente altos,
--    que casi siempre son errores de tipeo.
-- ------------------------------------------------------------

CREATE OR REPLACE FUNCTION promedios_por_tipo(costo_max NUMERIC DEFAULT 5000)
RETURNS TABLE (
    tipo_mantenimiento_id SMALLINT,
    promedio              NUMERIC,
    conteo                BIGINT
)
LANGUAGE sql
STABLE
AS $$
    SELECT m.tipo_mantenimiento_id,
           ROUND(AVG(m.costo)::numeric, 2) AS promedio,
           COUNT(*)                        AS conteo
      FROM mantenimientos m
     WHERE m.costo IS NOT NULL
       AND m.costo > 0
       AND m.costo <= costo_max
     GROUP BY m.tipo_mantenimiento_id;
$$;

COMMIT;

-- ------------------------------------------------------------
-- Comprobación (ejecutar aparte para ver que quedó bien)
-- ------------------------------------------------------------
-- SELECT id, telefono, telefono_normalizado FROM usuarios ORDER BY id;
-- SELECT * FROM promedios_por_tipo();
-- EXPLAIN ANALYZE SELECT * FROM usuarios WHERE telefono_normalizado = '991234567';
