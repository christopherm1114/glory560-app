-- ============================================================
-- seed.sql — Datos iniciales (catálogo del manual del Glory 560)
-- Ejecuta este archivo DESPUÉS de schema.sql, en el editor SQL de Supabase.
-- ============================================================

-- ---------- Las 4 variantes del Glory 560 (datos del manual 2023) ----------
INSERT INTO variantes (id, nombre, motor, transmision, aceite_motor, capacidad_aceite_l,
    bujia_tipo, liquido_transmision, capacidad_transmision_l, refrigerante_l,
    medida_llanta, presion_llantas) VALUES
(1, 'SFG18 5MT',  '1.8 Aspirado', '5MT', 'SM 5W-30', 3.8,
    'Bosch FR8SE0',    'GL-4 75W/90',        1.80, 6.5, '215/60 R17', 'Del 230 / Tras 230-250 kPa'),
(2, 'SFG18 CVT',  '1.8 Aspirado', 'CVT', 'SM 5W-30', 3.8,
    'Bosch FR8SE0',    'IDEMITSU CVTF-EX1',  4.30, 6.5, '215/60 R17', 'Del 230 / Tras 230-250 kPa'),
(3, 'SFG15T 6MT', '1.5 Turbo',    '6MT', 'SM 5W-30', 4.5,
    'Torch LDK8RAPP',  'GL-4 85W/90',        2.20, 5.0, '215/60 R17', 'Del 230 / Tras 230-250 kPa'),
(4, 'SFG15T CVT', '1.5 Turbo',    'CVT', 'SM 5W-30', 4.5,
    'Torch LDK8RAPP',  'IDEMITSU CVTF-EX1',  4.68, 5.0, '215/60 R17', 'Del 230 / Tras 230-250 kPa');

-- ---------- Controles de mantenimiento (comunes a todas las variantes) ----------
INSERT INTO tipos_mantenimiento (id, nombre, categoria, descripcion) VALUES
(1,  'Cambio de aceite de motor',   'Motor',        'Cambio de aceite (primer cambio a los 10.000 km, luego periódico).'),
(2,  'Filtro de aceite',            'Motor',        'Se cambia junto con el aceite de motor.'),
(3,  'Filtro de aire',              'Motor',        'Filtro de aire del motor. Se acorta en ambientes con polvo.'),
(4,  'Filtro de combustible',       'Motor',        'Filtro de la línea de combustible.'),
(5,  'Filtro de cabina (A/C)',      'A/C',          'Filtro de aire acondicionado / polen.'),
(6,  'Bujías',                      'Motor',        'Revisión y cambio de bujías (el tipo depende del motor).'),
(7,  'Líquido de frenos',           'Chasis',       'Revisión continua; cambio cada 40.000 km o 2 años.'),
(8,  'Refrigerante de motor',       'Motor',        'Revisión continua; cambio periódico según clima.'),
(9,  'Aceite de transmisión',       'Transmisión',  'Manual (GL-4) o CVT (CVTF-EX1) según la variante.'),
(10, 'Rotación de llantas',         'Chasis',       'Rotación en cruz y revisión de desgaste/presión.');

-- ---------- Intervalos por variante ----------
-- 1) Intervalos COMUNES (iguales para las 4 variantes): se generan con un
--    "producto cruzado" (cada variante × cada control común).
INSERT INTO intervalos (variante_id, tipo_mantenimiento_id, intervalo_km, intervalo_meses)
SELECT v.id, c.tipo, c.km, c.meses
FROM variantes v
CROSS JOIN (VALUES
    (1,  5000,  6),   -- Aceite de motor
    (2,  5000,  6),   -- Filtro de aceite
    (3, 10000, 12),   -- Filtro de aire
    (4, 10000,  6),   -- Filtro de combustible
    (5, 20000, 12),   -- Filtro de cabina
    (7, 40000, 24),   -- Líquido de frenos
    (8, 40000, 24),   -- Refrigerante
    (10,10000, 12)    -- Rotación de llantas
) AS c(tipo, km, meses);

-- 2) Bujías: el intervalo depende del motor (1.8 aspirado vs 1.5 turbo).
INSERT INTO intervalos (variante_id, tipo_mantenimiento_id, intervalo_km, intervalo_meses) VALUES
(1, 6, 20000, 24),   -- SFG18 5MT  (1.8)
(2, 6, 20000, 24),   -- SFG18 CVT  (1.8)
(3, 6, 10000, 12),   -- SFG15T 6MT (1.5T)
(4, 6, 10000, 12);   -- SFG15T CVT (1.5T)

-- 3) Aceite de transmisión: depende de la caja (manual vs CVT).
INSERT INTO intervalos (variante_id, tipo_mantenimiento_id, intervalo_km, intervalo_meses, insumo) VALUES
(1, 9, 20000, 12, 'GL-4 75W/90'),         -- caja manual 5MT
(2, 9, 60000, 24, 'IDEMITSU CVTF-EX1'),   -- caja CVT
(3, 9, 20000, 12, 'GL-4 85W/90'),         -- caja manual 6MT
(4, 9, 60000, 24, 'IDEMITSU CVTF-EX1');   -- caja CVT

-- (Opcional) Convierte tu propio usuario en administrador después de registrarte:
-- UPDATE usuarios SET rol = 'admin', estado = 'aprobado' WHERE telegram_id = TU_ID;
