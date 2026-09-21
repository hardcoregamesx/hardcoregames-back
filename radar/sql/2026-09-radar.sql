-- Esquema del radar de ofertas (fase 0). Idempotente (IF NOT EXISTS en todo),
-- se puede correr varias veces sin romper nada. Este proyecto no usa `migrate`
-- en ningun app: este archivo es la fuente de verdad del esquema, igual que
-- products/sql/2026-09-cuotas-reserva.sql y membership/sql/. Ver
-- docs/radar-ofertas.md. Ejecutar en `hc-postgres` ANTES de desplegar el Django
-- que ya espera estas tablas.
--
-- Todo lo de aqui es ADITIVO: crea tablas nuevas con prefijo radar_ y no toca
-- ninguna tabla existente.

-- Parametros de negocio, editables desde el admin (una sola fila).
CREATE TABLE IF NOT EXISTS radar_parametrosradar (
  id serial PRIMARY KEY,
  factor_precio_venta numeric(4,2) NOT NULL DEFAULT 0.80,   -- precio_colombia x esto = precio de venta
  margen_minimo_cop bigint NOT NULL DEFAULT 20000,          -- ganancia minima para considerar viable
  descuento_minimo_pct numeric(5,2) NOT NULL DEFAULT 10,    -- piso de descuento en la tienda de origen
  actualizado timestamp with time zone NOT NULL DEFAULT now()
);

-- Cuantos pesos vale una unidad de cada moneda de compra.
-- Las marcadas manual = true NO las pisa el actualizador automatico: es el caso
-- del dolar, que se consigue por debajo de la TRM.
CREATE TABLE IF NOT EXISTS radar_tasacambio (
  moneda varchar(3) PRIMARY KEY,
  cop_por_unidad numeric(18,6) NOT NULL,
  manual boolean NOT NULL DEFAULT false,
  nota varchar(200) NOT NULL DEFAULT '',
  actualizado timestamp with time zone NOT NULL DEFAULT now()
);

-- Un juego visto por el radar, con su ficha y su precio de referencia en Colombia.
CREATE TABLE IF NOT EXISTS radar_juegodetectado (
  id serial PRIMARY KEY,
  tienda varchar(8) NOT NULL,                -- 'XBOX' | 'PS'
  id_externo varchar(64) NOT NULL,           -- bigId en Xbox; concept id en PlayStation
  titulo varchar(300) NOT NULL,
  descripcion text NOT NULL DEFAULT '',
  imagen varchar(700) NOT NULL DEFAULT '',
  generos varchar(300) NOT NULL DEFAULT '',
  clasificacion varchar(80) NOT NULL DEFAULT '',
  plataformas varchar(160) NOT NULL DEFAULT '',
  desarrollador varchar(200) NOT NULL DEFAULT '',
  rating double precision NOT NULL DEFAULT 0,      -- senal de popularidad de la propia tienda
  rating_conteo integer NOT NULL DEFAULT 0,
  precio_co numeric(18,4) NULL,              -- ancla: contra esto compara el cliente
  precio_co_oferta numeric(18,4) NULL,
  comprable_co boolean NOT NULL DEFAULT true,
  producto_existente_id integer NULL,        -- id en products_products, sin FK a proposito
  visto_primero timestamp with time zone NOT NULL DEFAULT now(),
  visto_ultimo timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT radar_juegodetectado_tienda_id_externo_uniq UNIQUE (tienda, id_externo)
);

CREATE INDEX IF NOT EXISTS radar_juegodetectado_visto_ultimo_idx
  ON radar_juegodetectado (visto_ultimo);

-- Precio de un juego en una region de compra, ya convertido a pesos.
CREATE TABLE IF NOT EXISTS radar_precioregional (
  id serial PRIMARY KEY,
  juego_id integer NOT NULL REFERENCES radar_juegodetectado(id) ON DELETE CASCADE,
  region varchar(2) NOT NULL,                -- CO | TR | IN | SA | US
  moneda varchar(3) NOT NULL,
  precio_lista numeric(18,4) NULL,
  precio_oferta numeric(18,4) NULL,
  descuento_pct numeric(6,2) NOT NULL DEFAULT 0,
  -- Critico: hay juegos que se listan con precio pero no se pueden comprar en
  -- esa tienda (M-rated en Arabia Saudita). Sin esto serian ofertas fantasma.
  comprable boolean NOT NULL DEFAULT false,
  fecha_fin timestamp with time zone NULL,   -- cuando vence la promocion
  costo_cop bigint NULL,                     -- precio_oferta convertido a pesos
  actualizado timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT radar_precioregional_juego_region_uniq UNIQUE (juego_id, region)
);

CREATE INDEX IF NOT EXISTS radar_precioregional_juego_id_idx
  ON radar_precioregional (juego_id);

-- Bitacora de cada corrida. Un radar roto en silencio muestra precios viejos y
-- hace vender a perdida: aqui queda el rastro para poder alertar.
CREATE TABLE IF NOT EXISTS radar_ejecucionradar (
  id serial PRIMARY KEY,
  tienda varchar(8) NOT NULL,
  regiones varchar(120) NOT NULL DEFAULT '',
  inicio timestamp with time zone NOT NULL DEFAULT now(),
  fin timestamp with time zone NULL,
  ok boolean NOT NULL DEFAULT false,
  juegos_vistos integer NOT NULL DEFAULT 0,
  precios_guardados integer NOT NULL DEFAULT 0,
  error text NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS radar_ejecucionradar_inicio_idx
  ON radar_ejecucionradar (inicio DESC);

-- ---------------------------------------------------------------------------
-- Fase 1: aprobacion y publicacion. Aditivo e idempotente, igual que arriba.
-- ---------------------------------------------------------------------------

ALTER TABLE radar_juegodetectado
  -- nuevo | aprobado | descartado | publicado | vencido
  ADD COLUMN IF NOT EXISTS estado varchar(12) NOT NULL DEFAULT 'nuevo',
  -- Precio que fija el dueno a mano. El radar solo sugiere.
  ADD COLUMN IF NOT EXISTS precio_venta bigint NULL,
  -- Region elegida para comprarlo (se congela al aprobar).
  ADD COLUMN IF NOT EXISTS region_compra varchar(2) NOT NULL DEFAULT '',
  -- Producto creado en el catalogo al publicar.
  ADD COLUMN IF NOT EXISTS producto_publicado_id integer NULL,
  ADD COLUMN IF NOT EXISTS consola_id integer NULL,
  ADD COLUMN IF NOT EXISTS licencia_id integer NULL,
  ADD COLUMN IF NOT EXISTS publicado_en timestamp with time zone NULL;

CREATE INDEX IF NOT EXISTS radar_juegodetectado_estado_idx
  ON radar_juegodetectado (estado);

-- Valores por defecto al publicar, para no elegirlos uno por uno.
ALTER TABLE radar_parametrosradar
  ADD COLUMN IF NOT EXISTS consola_xbox_id integer NULL,
  ADD COLUMN IF NOT EXISTS consola_ps_id integer NULL,
  ADD COLUMN IF NOT EXISTS licencia_default_id integer NULL,
  ADD COLUMN IF NOT EXISTS tipo_producto_id integer NULL,
  -- Cuantas unidades queda disponible cada producto publicado. No es stock
  -- real: es cuantas ventas se aceptan antes de tener que revisarlo a mano.
  ADD COLUMN IF NOT EXISTS stock_publicacion integer NOT NULL DEFAULT 10,
  -- Una cuenta no se vende al precio de un codigo, pero primaria y secundaria
  -- comparten precio: un solo factor para las dos. Vacio a proposito: hasta
  -- que se llene, el radar publica solo el codigo y no inventa precios.
  ADD COLUMN IF NOT EXISTS licencia_primaria_id integer NULL,
  ADD COLUMN IF NOT EXISTS licencia_secundaria_id integer NULL,
  ADD COLUMN IF NOT EXISTS factor_cuenta numeric(4,2) NULL;

-- Columnas de una version anterior de este mismo archivo, que llego a tener un
-- factor por cada licencia. Nunca se llenaron: se quitan para no dejar campos
-- muertos que confundan en el admin.
ALTER TABLE radar_parametrosradar
  DROP COLUMN IF EXISTS factor_primaria,
  DROP COLUMN IF EXISTS factor_secundaria;

-- Bandera en el catalogo: estos productos NO son de entrega inmediata, se
-- consiguen sobre pedido y se entregan en el horario de la tienda. El frontend
-- la usa para cambiar la promesa de entrega y no generar reclamos.
ALTER TABLE products_products
  ADD COLUMN IF NOT EXISTS sobre_pedido boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS radar_tienda varchar(8) NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS products_products_sobre_pedido_idx
  ON products_products (sobre_pedido);

-- ---------------------------------------------------------------------------
-- El dolar de saldo de cada tienda. No es un dolar normal: el saldo se compra
-- como gift card con descuento en buysellvouchers, y el descuento NO es el
-- mismo en Xbox que en PSN. El costo real se compone factor x TasaCambio.USD.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS radar_tasatienda (
  tienda varchar(8) PRIMARY KEY,           -- 'XBOX' | 'PS'
  factor numeric(8,6) NOT NULL,            -- dolares que cuesta 1 dolar de saldo
  muestras integer NOT NULL DEFAULT 0,
  manual boolean NOT NULL DEFAULT false,
  nota varchar(300) NOT NULL DEFAULT '',
  actualizado timestamp with time zone NOT NULL DEFAULT now()
);
