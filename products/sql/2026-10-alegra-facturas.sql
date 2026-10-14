-- Facturación electrónica con Alegra. Idempotente. La app `products` no tiene
-- migraciones: este archivo es la fuente de verdad del esquema. Ejecutar en
-- `hc-postgres` ANTES de desplegar el Django que usa products.AlegraInvoice.

CREATE TABLE IF NOT EXISTS products_alegrainvoice (
  id serial PRIMARY KEY,
  transaction_id integer NOT NULL UNIQUE REFERENCES products_transactions(id_transaction),
  estado varchar(12) NOT NULL DEFAULT 'pendiente',  -- pendiente | emitida | borrador | fallida
  monto integer NOT NULL,
  items_json text NOT NULL DEFAULT '[]',
  alegra_id varchar(40) NULL,
  numero varchar(40) NULL,
  intentos integer NOT NULL DEFAULT 0,
  ultimo_error text NOT NULL DEFAULT '',
  fecha_creacion timestamptz NOT NULL DEFAULT now(),
  fecha_actualizacion timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_alegrainvoice_estado ON products_alegrainvoice(estado);
