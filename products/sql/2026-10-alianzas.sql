-- Esquema de "Beneficios aliados". Idempotente (IF NOT EXISTS), se puede correr
-- varias veces. La app `products` no tiene migraciones de Django: este archivo
-- es la fuente de verdad del esquema. Ejecutar en `hc-postgres` ANTES de
-- desplegar el Django/FastAPI que ya esperan estas tablas.

CREATE TABLE IF NOT EXISTS products_aliado (
  id serial PRIMARY KEY,
  nombre varchar(120) NOT NULL,
  categoria varchar(60) NOT NULL DEFAULT '',
  logo_url varchar(500) NOT NULL DEFAULT '',
  beneficio varchar(200) NOT NULL,            -- "15% en ropa deportiva"
  condiciones text NOT NULL DEFAULT '',
  secreto integer NOT NULL                    -- 3 digitos, solo lo conocen el aliado y HG
    CHECK (secreto BETWEEN 100 AND 999),
  codigo_fijo varchar(40) NOT NULL DEFAULT '', -- si no esta vacio, reemplaza al automatico
  activo boolean NOT NULL DEFAULT true,
  orden integer NOT NULL DEFAULT 0,
  fecha_creacion timestamptz NOT NULL DEFAULT now()
);

-- Aperturas de la tarjeta de un aliado (metrica). Una fila por apertura.
CREATE TABLE IF NOT EXISTS products_aliadoapertura (
  id serial PRIMARY KEY,
  aliado_id integer NOT NULL REFERENCES products_aliado(id),
  user_id integer NOT NULL REFERENCES auth_user(id),
  mes date NOT NULL,                          -- primer dia del mes (hora de Colombia)
  fecha timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS products_aliadoapertura_aliado_mes
  ON products_aliadoapertura (aliado_id, mes);

-- Pagina del aliado (sitio web o Instagram) a la que lleva el boton de la tarjeta.
ALTER TABLE products_aliado
  ADD COLUMN IF NOT EXISTS url varchar(300) NOT NULL DEFAULT '';
