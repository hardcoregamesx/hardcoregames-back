-- Esquema de "Cuotas y Reserva" (fase 1). Idempotente (IF NOT EXISTS en todo),
-- se puede correr varias veces sin romper nada. La app `products` no tiene
-- migraciones de Django: este archivo es la fuente de verdad del esquema,
-- ver docs/cuotas-y-reserva.md §3. Ejecutar en `hc-postgres` ANTES de
-- desplegar el Django/FastAPI que ya esperan estas columnas/tablas.

ALTER TABLE products_gamedetail
  ADD COLUMN IF NOT EXISTS cuotas_activas boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS num_cuotas integer NOT NULL DEFAULT 3,
  ADD COLUMN IF NOT EXISTS valor_cuota integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cuota_inicial integer NULL,
  ADD COLUMN IF NOT EXISTS reserva_activa boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS monto_reserva integer NOT NULL DEFAULT 20000;

ALTER TABLE products_products
  ADD COLUMN IF NOT EXISTS fecha_lanzamiento date NULL;

ALTER TABLE products_shoppingcar
  ADD COLUMN IF NOT EXISTS modo_pago varchar(10) NOT NULL DEFAULT 'contado';

CREATE TABLE IF NOT EXISTS products_paymentplan (
  id serial PRIMARY KEY,
  user_id integer NOT NULL REFERENCES auth_user(id),
  gamedetail_id integer NOT NULL REFERENCES products_gamedetail(id_game_detail),
  tipo varchar(10) NOT NULL,                 -- 'cuotas' | 'reserva'
  estado varchar(20) NOT NULL,               -- ver §3.1
  titulo_snapshot varchar(300) NOT NULL DEFAULT '',  -- "Título | Licencia | Consola"
  precio_total integer NOT NULL,             -- congelado al crear (ver §3.2)
  descuento integer NOT NULL DEFAULT 0,      -- cupón+saldo+VIP aplicados al pago de hoy
  num_cuotas integer NOT NULL DEFAULT 1,
  valor_cuota integer NOT NULL DEFAULT 0,
  cuota_inicial integer NULL,
  monto_reserva integer NULL,
  total_pagado integer NOT NULL DEFAULT 0,
  mora_acumulada integer NOT NULL DEFAULT 0,
  mora_exenta boolean NOT NULL DEFAULT false,
  retirado boolean NOT NULL DEFAULT false,
  token varchar(64) NOT NULL UNIQUE,
  transaction_origen_id integer NULL REFERENCES products_transactions(id_transaction),
  saledetail_id integer NULL REFERENCES products_saledetail(id_sale_detail),
  cuenta_asignada_id integer NULL REFERENCES products_productaccounts(id_product_accounts),
  fecha_asignacion timestamptz NULL,
  fecha_limite_pago timestamptz NULL,
  notas text NOT NULL DEFAULT '',
  fecha_creacion timestamptz NOT NULL DEFAULT now(),
  fecha_actualizacion timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_paymentplan_user ON products_paymentplan(user_id);
CREATE INDEX IF NOT EXISTS ix_paymentplan_estado ON products_paymentplan(estado);

CREATE TABLE IF NOT EXISTS products_paymentinstallment (
  id serial PRIMARY KEY,
  plan_id integer NOT NULL REFERENCES products_paymentplan(id) ON DELETE CASCADE,
  numero integer NOT NULL,
  monto integer NOT NULL,
  mora integer NOT NULL DEFAULT 0,
  fecha_vencimiento date NULL,               -- NULL en el saldo de una reserva sin asignar
  estado varchar(12) NOT NULL DEFAULT 'pendiente',  -- 'pendiente' | 'pagada' | 'cancelada'
  fecha_pago timestamptz NULL,
  transaction_id integer NULL REFERENCES products_transactions(id_transaction),
  metodo varchar(30) NULL,                   -- 'transferencia_brebb' | 'bold' | 'manual' | 'checkout'
  ultimo_recordatorio timestamptz NULL,
  UNIQUE (plan_id, numero)
);

INSERT INTO products_variablessistema (nombre_variable, descripcion, valor, estado)
SELECT v.n, v.d, v.v, true FROM (VALUES
  ('CUOTAS_DIAS_GRACIA', 'Días de gracia tras el vencimiento antes de cobrar mora', '3'),
  ('CUOTAS_MORA_SEMANAL', 'Mora fija en COP por cada semana de atraso', '5000'),
  ('CUOTAS_DIAS_RETIRO', 'Días sin pago ni respuesta para marcar retirado', '15'),
  ('CUOTAS_FRECUENTE_COMPRAS', 'Compras completadas para ser cliente frecuente (exento de mora)', '3'),
  ('CUOTAS_FRECUENTE_MESES', 'Meses máximos desde la última compra para seguir siendo frecuente', '6'),
  ('RESERVA_DIAS_PAGO_SALDO', 'Días para pagar el saldo tras asignar cuenta', '2'),
  ('RESERVA_DIAS_PENDIENTE', 'Días que la reserva sigue viva tras liberar la cuenta', '30')
) AS v(n, d, v)
WHERE NOT EXISTS (SELECT 1 FROM products_variablessistema x WHERE x.nombre_variable = v.n);
