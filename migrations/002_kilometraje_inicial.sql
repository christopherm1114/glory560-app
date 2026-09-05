-- 002_kilometraje_inicial.sql
--
-- Línea base de kilometraje para los controles que nunca se han registrado.
--
-- Antes, `mantenimiento.calcular_estado_vehiculo` usaba km_base = 0 cuando un
-- control no tenía historial. Un vehículo dado de alta con 45.000 km veía todos
-- sus controles vencidos desde el primer día.
--
-- No sirve usar `kilometraje_actual` en su lugar: al ser un valor que sube, el
-- objetivo se alejaría a la par que el odómetro y el control nunca vencería.
-- Hace falta un valor congelado en el momento del alta, que es esta columna.

ALTER TABLE vehiculos
    ADD COLUMN IF NOT EXISTS kilometraje_inicial INT;

-- Para los vehículos que ya existen no sabemos con cuánto se dieron de alta.
-- El kilometraje actual es la mejor aproximación disponible, y congelarlo aquí
-- es lo que evita que el objetivo siga moviéndose.
UPDATE vehiculos
   SET kilometraje_inicial = COALESCE(kilometraje_actual, 0)
 WHERE kilometraje_inicial IS NULL;
