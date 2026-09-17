# Cuotas y Reserva — especificación técnica (v1, 17/09/2026)

Fuente de verdad del proyecto "pago por cuotas" de hardcoregames.co. Cubre los
cuatro repos: `hardcoregames-back` (Django), `hardcoregames-back-fastapi`,
`frontend-v2` y `hardcoregames-ventas`. Cualquier agente que implemente una
parte lee este documento completo antes de tocar código.

## 1. Reglas de negocio acordadas con el dueño

- **Cuotas y Reserva son modos de pago de la variante normal** (`products_gamedetail`
  = producto × consola × licencia). No son productos aparte. El stock es uno solo.
  Los productos actuales titulados "A CUOTAS - ..." se apagan en la fase de migración.
- **Cuotas**: N cuotas (por defecto 3) de `valor_cuota`, con `cuota_inicial` opcional
  (si está vacía, la inicial vale igual que las demás). La primera cuota se paga
  completa en el checkout y **el producto se entrega de inmediato** (igual que una
  compra de contado). Las siguientes vencen cada 30 días desde la compra. Solo
  aplica a licencias Primaria (id 1) y Secundaria (id 2); nunca a keys/códigos.
- **Reserva**: el cliente paga `monto_reserva` (por defecto 20.000) por un producto
  que **aún no ha salido** (`products_products.fecha_lanzamiento` futura). No se
  entrega nada. El precio de contado queda **congelado** en el plan. Cuando el admin
  carga cuentas, el sistema asigna una a cada reserva por orden de fecha y le pide al
  cliente el saldo; al pagarlo se entrega. Sin mora: si no paga en 2 días la cuenta
  vuelve al stock general (o el admin la libera con un botón) y la reserva queda
  "pendiente de pago" 30 días más; después se cancela y el dinero pasa a saldo de
  tienda (`users_user_customized.balance_exchange`), solo usable en digitales.
  Al asignar, el cliente puede pagar el saldo completo o pasar a cuotas si la
  variante tiene cuotas activas (los 20.000 cuentan como parte de la inicial).
- **Nunca se muestra el total del plan** en tarjetas ni en la página de producto.
  Solo en el resumen del checkout y en "Pagos pendientes".
- **Carrito mixto permitido**: contado + cuotas + reserva en un mismo checkout.
  - Se paga hoy: contado completo + cuota inicial + montos de reserva.
  - Cupones, saldo y descuento VIP se restan **de lo que se paga hoy**, con tope
    (nunca arrastran saldo a las cuotas siguientes).
  - **Sistecrédito queda deshabilitado** si hay algún ítem que no sea contado.
  - Una misma variante no puede estar dos veces con modos distintos.
  - El registro en el programa de ventas es **por ítem**.
- **Mora en cuotas** (parámetros en `products_variablessistema`, editables):
  `CUOTAS_DIAS_GRACIA`=3, `CUOTAS_MORA_SEMANAL`=5000 (se suma a la cuota
  vencida por cada semana de atraso), `CUOTAS_DIAS_RETIRO`=15 (sin pago ni
  respuesta → retirado), `CUOTAS_FRECUENTE_COMPRAS`=3 y `CUOTAS_FRECUENTE_MESES`=6
  (exento de mora quien tenga ≥3 compras completadas y alguna en los últimos 6
  meses). Membresía de YouTube: hueco preparado, aún no vinculada.
- **Retirado**: oculta la credencial en `/purchases` con el mensaje "Producto
  retirado por falta de pago, contáctanos". Reactivable desde el admin.
- **Programa de ventas**: Cuotas = Venta completa desde el primer pago, marcada
  `es_separado` hasta completar, con un abono por cada cuota. Reserva = Apartado
  con abonos hasta completarse.
- **Recordatorios** (fase 2): correo + push del navegador. 3 días antes del
  vencimiento y diario desde el vencimiento hasta que se marque pagado.
- **Invitados**: el checkout de invitado crea una cuenta real con contraseña
  aleatoria. Por eso cada plan tiene un `token` y los correos llevan un enlace
  `https://www.hardcoregames.co/pagos/<token>` que abre el plan sin login. En la
  pantalla de éxito se le pide al invitado crear contraseña.

## 2. Fases

1. **Base** (esta especificación): esquema, admin, tarjetas y página de producto,
   checkout mixto, creación de planes, "Pagos pendientes" con transferencia y Bold,
   enlace con token, registro en ventas.
2. Recordatorios y mora automática, retiro/reactivación, push.
3. Reservas: pantalla en admin, carga de cuentas (mismo Excel de `Files`),
   asignación, cobro del saldo, conversión a cuotas.
4. Migración: cargar valores en variantes normales, apagar productos "A CUOTAS",
   quitar valores fijos de `GamepassUltimatePage.tsx` y `PsPlusPage.tsx`.

## 3. Esquema de base de datos (Postgres `hardcoregames`, `hc-postgres`)

La app `products` de Django **no tiene migraciones**. El esquema se aplica con SQL
directo (archivo `products/sql/2026-09-cuotas-reserva.sql`, idempotente con
`IF NOT EXISTS`), y los modelos Django/SQLAlchemy se espejan a mano. Los modelos
Django nuevos llevan `managed = False`.

```sql
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
```

### 3.1 Estados del plan

- `cuotas`: `activo` → `completado`. Intermedios: `en_mora`, `retirado`, `cancelado`.
- `reserva`: `esperando_stock` → `asignado` (cuenta asignada, saldo con fecha límite)
  → `completado`. Intermedios: `pendiente_pago` (cuenta liberada, sigue viva),
  `cancelado`.

### 3.2 Cómo se congela el precio y se arman las cuotas

Sea `gd` la variante. `precio_contado = gd.precio_descuento if 0 < gd.precio_descuento < gd.precio else gd.precio`.

- **Cuotas**: `inicial = gd.cuota_inicial or gd.valor_cuota`;
  `precio_total = inicial + gd.valor_cuota * (gd.num_cuotas - 1)`.
  Cuotas: #1 monto `inicial - descuento_item` (estado `pagada`, `metodo='checkout'`,
  `fecha_pago=now`, `transaction_id` = la del checkout), #k (k=2..N) monto
  `gd.valor_cuota`, `fecha_vencimiento = fecha_compra + 30*(k-1) días`.
- **Reserva**: `precio_total = precio_contado`; `monto_reserva = gd.monto_reserva`.
  Cuota #1 monto `monto_reserva - descuento_item` (pagada, checkout); cuota #2
  monto `precio_total - monto_reserva`, `fecha_vencimiento NULL`, `pendiente`.
- **Descuento por ítem**: el descuento total del checkout (cupón + saldo + VIP) se
  reparte entre los ítems proporcionalmente a su "pago de hoy", redondeando y
  cargando el residuo al último ítem. El plan guarda su parte en `descuento`.
- **Plan completado** cuando `total_pagado + descuento >= precio_total`.

## 4. Django (`hardcoregames-back`)

### 4.1 Modelos (`products/models.py`)

- `GameDetail`: añadir `cuotas_activas`, `num_cuotas`, `valor_cuota`, `cuota_inicial`,
  `reserva_activa`, `monto_reserva` (mismos tipos que el SQL). Método
  `precio_contado()` y `plan_cuotas()` → dict `{inicial, valor_cuota, num_cuotas, total}`
  o `None`.
- `Products`: añadir `fecha_lanzamiento = DateField(null=True, blank=True)`.
- `ShoppingCar`: añadir `modo_pago = CharField(max_length=10, default='contado')`.
- Nuevos `PaymentPlan` (`db_table='products_paymentplan'`, `managed=False`) y
  `PaymentInstallment` (`db_table='products_paymentinstallment'`, `managed=False`)
  espejando §3. `token` se genera con `secrets.token_urlsafe(32)`.

### 4.2 Admin (`products/admin.py`)

- `GameDetailAdmin`: fieldset nuevo "Cuotas y reserva" con los seis campos y texto de
  ayuda ("Solo Primaria/Secundaria", "Reserva solo si el producto tiene fecha de
  lanzamiento futura"). Validación en `clean()`: `cuotas_activas` exige
  `valor_cuota > 0`, `num_cuotas >= 2`, `licencia_id in (1, 2)`; `reserva_activa` exige
  `monto_reserva > 0` y `producto.fecha_lanzamiento` futura.
- `ProductsAdmin`: `fecha_lanzamiento` visible y editable.
- `PaymentPlanAdmin`: list_display (id, usuario, título, tipo, estado, total,
  pagado, próximo vencimiento, retirado), list_filter (tipo, estado, retirado),
  search (email, título, token), inline `PaymentInstallment` editable (estado,
  fecha_pago, fecha_vencimiento, mora, metodo). Acciones: "Marcar cuota
  seleccionada como pagada (manual)" (vía inline), "Perdonar mora", "Cancelar plan",
  "Retirar producto", "Reactivar producto". Al guardar, recalcular `total_pagado`,
  `estado` y `mora_acumulada`.
- Registrar `VariablesSistema` ya existe; no tocar.

### 4.3 Checkout (`products/views.py`)

Cada ítem de `request_transaction.data` trae `modo_pago` (`contado` por defecto si
falta, para no romper clientes viejos).

`_calculate_cart_amount(parsed_transaction, allow_plans=True)`:

- Valida por ítem: `cuotas` exige `gd.cuotas_activas`, `gd.licencia_id in (1,2)`,
  `gd.stock > 0`; `reserva` exige `gd.reserva_activa` y
  `gd.producto.fecha_lanzamiento > hoy`. Error 400 con mensaje claro si no.
- Rechaza 400 si la misma `id_combination` aparece con dos modos.
- "Pago de hoy" por ítem: contado → precio_contado; cuotas → inicial; reserva →
  monto_reserva. `calculated_subtotal` = suma de pagos de hoy.
- El cupón se evalúa sobre los pagos de hoy (misma lógica de elegibilidad actual).
- Devuelve además `items_calculados`: lista `{id_combination, modo_pago, pago_hoy,
  descuento}` con el reparto de §3.2. Los flujos que crean `Transactions` guardan
  esa lista dentro del JSON de `request` (`items_calculados`) junto al resto.
- `sistecredito_create` llama con `allow_plans=False` → 400 "Sistecrédito no
  disponible para cuotas o reserva" si hay ítems no contado.

`confirm_sale(request_data)`:

- `contado`: sin cambios.
- `cuotas`: misma entrega que contado (stock, puntos, borrar carrito, `create_sale`,
  HTML de credenciales) **más** `PaymentPlan(tipo='cuotas', estado='activo')` con sus
  cuotas (§3.2), `saledetail_id` enlazado, `transaction_origen_id`. El correo de
  compra añade un bloque "Tu plan de cuotas" con las fechas y montos pendientes y el
  enlace `https://www.hardcoregames.co/pagos/<token>`.
- `reserva`: **no** toca stock, **no** crea `SaleDetail`, sí borra del carrito; crea
  `PaymentPlan(tipo='reserva', estado='esperando_stock')` con precio congelado. Correo
  "Reserva confirmada" con fecha de lanzamiento y el enlace del plan.
- Al final, si hubo algún ítem no contado: `_notify_ventas_planes(transaction)` (§7).
  `_notify_ventas_module` (el de forma Bold) se sigue llamando solo si **todos** los
  ítems son contado; si hay mezcla, el evento de planes lleva también los ítems de
  contado.
- Si el pago fue por Bold, el webhook real de Bold ya le llega a ventas; el evento de
  planes lo corrige del lado de ventas (§7).

### 4.4 Pago de cuotas siguientes (`products/views_planes.py`, rutas en `products/urls.py` bajo `planes/`)

Autenticación: JWT Bearer (`_get_verified_jwt_user`) **o** `planToken` en el body/query
que coincida con `plan.token`. Nunca ambos obligatorios.

- `POST planes/cuotaTransferenciaCreate/` body `{installment_id, nombre_pagador, planToken?}`:
  valida que la cuota esté `pendiente` y sea la **más antigua pendiente** del plan
  (no se puede pagar la 3 antes de la 2); monto = `monto + mora`; crea
  `Transactions(status='pendiente', payment_id='transferencia_brebb',
  request=json{"tipo":"cuota","installment_id":..,"plan_id":..,"id_user":..,"nombre_pagador":..})`;
  registra la expectativa en pagos-nequi igual que `transferencia_create`. Respuesta
  con el mismo shape que `transferencia_create`.
- `POST planes/cuotaBoldHash/` body `{installment_id, amount, currency, planToken?}`:
  equivalente a `generate_hash_bold` (acepta monto exacto o monto + tarifa de
  tarjeta), `request` con el mismo JSON de tipo `cuota`.
- `transferencia_confirmar_envio` y `transferencia_status`: aceptar `planToken` como
  alternativa al JWT cuando la transacción es de tipo `cuota` de ese plan.
- **Dispatch en webhooks**: en `process_transferencia_event` y en el webhook de Bold,
  antes de llamar `confirm_sale`, si `json.loads(transaction.request).get('tipo') == 'cuota'`
  → `confirm_installment_payment(transaction)`.
- `confirm_installment_payment(transaction)`: marca la cuota `pagada` (`fecha_pago`,
  `transaction_id`, `metodo`), `plan.total_pagado += cuota.monto` (la mora no cuenta
  para el total), `mora_acumulada` se reduce en la mora de esa cuota, recalcula
  `estado` (`activo`/`completado`; si estaba `en_mora` y ya no hay vencidas → `activo`).
  Para reservas (`numero == 2`, fase 3): entrega con la cuenta asignada. Envía correo
  "Cuota N de M recibida" con lo que queda. Llama `_notify_ventas_planes` con evento
  `cuota`.
- `GET planes/misPlanes/` (JWT) y `GET planes/porToken/<token>/`: **no** se implementan
  aquí, viven en FastAPI (§5). Django solo cobra y confirma.

### 4.5 Compras (`sales_by_user`, `SerializerSales`)

Añadir a cada `SaleDetail` serializado: `plan_id`, `plan_retirado` (bool). Si el
plan está `retirado`, `cuenta` y `password` salen vacíos y `plan_retirado=true`.

### 4.6 Correos

Reutilizar `SendEmail` y la plantilla `EMAIL_FOR_SALE` (inyectar en `div#body`).
Tres bloques HTML nuevos en `products/emails_planes.py`: plan de cuotas creado,
reserva confirmada, cuota recibida. Todos incluyen el botón "Ver mis pagos" al enlace
con token. Estilo en línea, colores de marca (fondo `#1a1030`, dorado `#f5c542`).

## 5. FastAPI (`hardcoregames-back-fastapi`)

- `app/models.py`: espejar columnas nuevas de `GameDetail`, `Product.fecha_lanzamiento`,
  `ShoppingCar.modo_pago`; nuevos `PaymentPlan`, `PaymentInstallment`.
- **Productos**: donde se serializan combinaciones (`/products/combination-price/{id}`
  y el detalle) añadir `cuotas_activas, num_cuotas, valor_cuota, cuota_inicial,
  reserva_activa, monto_reserva`. Donde se serializan productos para tarjetas
  (`/products/filter`, `/products/search`, destacados, ofertas, etc. — hay un
  serializador común, úsalo) añadir `fecha_lanzamiento` y los agregados
  `cuotas_desde` (mínimo `valor_cuota` entre variantes con `cuotas_activas` y stock>0,
  o null), `cuotas_num` (num_cuotas de esa variante) y `reserva_monto` (mínimo
  `monto_reserva` entre variantes con `reserva_activa`, solo si `fecha_lanzamiento`
  futura; o null). Cuidado con N+1: calcular con subconsultas/agregados.
- **Carrito** (`/shopping-car/`): `POST` acepta `modo_pago` (default `contado`) y
  rechaza 409 si la misma combinación ya está con otro modo; `GET` devuelve
  `modo_pago`, `pago_hoy` (según §3.2), y los seis campos del plan de la variante.
- **Nuevo router `/payment-plans/`**:
  - `GET /payment-plans/` (JWT): planes del usuario con sus cuotas, ordenados por
    próximo vencimiento. Campos: id, tipo, estado, titulo_snapshot, imagen y título
    del producto, precio_total, descuento, total_pagado, mora_acumulada, retirado,
    token, fecha_creacion, fecha_lanzamiento, cuotas[] {id, numero, monto, mora,
    fecha_vencimiento, estado, fecha_pago}, `proxima_cuota` (la pendiente más
    antigua o null), `puede_pagar` (bool: hay pendiente con fecha o es reserva
    asignada).
  - `GET /payment-plans/by-token/{token}` (sin auth): un solo plan, mismo shape,
    más `user_email` enmascarado (`ju***@gmail.com`) y `is_guest_account`.
  - `GET /payment-plans/pending-count` (JWT): `{count}` de cuotas pendientes vencidas
    o que vencen en ≤7 días, para el badge del botón dorado.
- **Auth**: `POST /auth/set-password` (JWT) body `{new_password, confirm_password}`:
  solo si el perfil tiene `is_guest_account=true`; fija la contraseña y pone
  `is_guest_account=false`. Devuelve `{message}`.
- Documentar los endpoints nuevos en `docs/endpoints-planes.md`.

## 6. Frontend (`frontend-v2`)

Diseño: usar la skill `hardcoregames-home-design` (tokens en `src/app/globals.css`).
Dorado `--cta` para todo lo relacionado con cuotas/reserva. Textos en
`src/lib/language-context.tsx` (es/en) como el resto del sitio.

- **Tipos** (`src/lib/api.ts`): `Combination` con los seis campos; `Product` con
  `fecha_lanzamiento`, `cuotas_desde`, `cuotas_num`, `reserva_monto`.
- **Tarjeta de producto** (el componente de card usado en home/filters): chip dorado
  "3 cuotas de $80.000" si `cuotas_desde`; chip "Reserva $20.000 · Sale 26 may" si
  `reserva_monto`. Nunca el total.
- **Página de producto** (`ProductDetail.tsx` + `ProductVariantSelector.tsx`):
  debajo del selector de variante, selector segmentado **Contado / Cuotas / Reserva**
  mostrando solo los modos que la variante elegida permita (si solo hay contado, no
  se muestra). Cada opción muestra precio de hoy y "cuándo recibes":
  - Contado: precio, "Recibes de inmediato".
  - Cuotas: "Inicial $X + 2 cuotas de $Y" o "3 cuotas de $Y"; "Recibes hoy · las
    siguientes cuotas cada 30 días"; enlace "¿Cómo funcionan las cuotas?" que abre un
    panel con las reglas (mora, retiro, exención a clientes frecuentes).
  - Reserva: "$20.000 hoy"; "Sale el D de M · pagas el resto cuando llegue tu cuenta".
  `performAddToCart`/`performBuyNow` mandan `modo_pago` y el `price` del ítem es el
  **pago de hoy**. El JSON-LD/SEO no cambia (sigue usando precio de contado).
- **Carrito** (`CartPage.tsx`, `cart.ts`): `CartItem`/`CheckoutItem` con `modo_pago`
  y `pago_hoy`; etiqueta bajo el título ("A cuotas · luego 2 × $80.000", "Reserva").
- **Checkout** (`CheckoutPage.tsx`): resumen con "Pagas hoy" y, por cada plan, una
  línea "Después: 2 cuotas de $Y cada 30 días" / "Saldo $Z cuando llegue tu cuenta".
  Botón Sistecrédito deshabilitado con tooltip "No disponible para cuotas o reserva"
  si hay algún ítem no contado. `request_transaction.data[].modo_pago` va al backend.
- **Éxito** (`/success`): si el pago incluía planes, bloque "Tu plan quedó activo"
  con próximas fechas y botón "Ver mis pagos". Si el usuario es invitado
  (`is_guest_account`), formulario "Crea tu contraseña para entrar después" que llama
  a `/auth/set-password`. (El permiso de push se añade en fase 2, dejar un hueco.)
- **Pagos pendientes**: nueva página `/pagos` (JWT) con la lista de planes y sus
  cuotas; botón "Pagar cuota" abre un modal con dos pestañas: Transferencia (reusa la
  lógica de `TransferenciaButton.tsx` apuntando a `planes/cuotaTransferenciaCreate/`)
  y Tarjeta/PSE (reusa el widget de Bold de `CheckoutPage.tsx` apuntando a
  `planes/cuotaBoldHash/`). Extraer lo compartido a `src/lib/planes.ts` y a un
  componente `PagarCuotaModal.tsx`. Al aprobarse, refrescar el plan.
- **Botón dorado "Pagos pendientes"** en `/purchases` (arriba de la lista) y en el
  menú de cuenta del `Header.tsx` (`ACCOUNT_LINKS`), con badge del
  `pending-count`. Se muestra siempre que el usuario tenga al menos un plan no
  completado; el badge solo si `count > 0`.
- **Enlace con token**: página `/pagos/[token]` sin login, mismo componente de plan
  que `/pagos`, usando `by-token` y pasando `planToken` a los endpoints de pago.
- **Compras**: ítems con `plan_retirado` muestran "Producto retirado por falta de
  pago. Escríbenos por WhatsApp para reactivarlo" en lugar de las credenciales.

## 7. Programa de ventas (`hardcoregames-ventas`)

Nuevo endpoint `POST /webhooks/planes/` (app `bold_integration` o nueva app
`planes`), protegido con header `X-Planes-Token` = `settings.PLANES_WEBHOOK_SECRET`
(variable de entorno; en Django de la tienda `VENTAS_PLANES_WEBHOOK_SECRET` y
`VENTAS_PLANES_WEBHOOK_URL`, default `https://ventas.srv936408.hstgr.cloud/webhooks/planes/`).

Payload que envía la tienda (`_notify_ventas_planes`):

```json
{
  "referencia_pago": "<Transactions.id_invoice>",
  "metodo": "TRANSFERENCIA_BREB | BOLD",
  "payer_email": "cliente@correo.com",
  "monto_total_pago": 120000,
  "items": [
    {"modo_pago": "contado", "descripcion": "Título | Licencia | Consola | Días", "monto": 40000},
    {"modo_pago": "cuotas", "plan_ref": "PLAN-12", "descripcion": "...", "monto": 60000,
     "evento": "inicial", "numero_cuota": 1, "num_cuotas": 3, "total_plan": 200000},
    {"modo_pago": "reserva", "plan_ref": "PLAN-13", "descripcion": "...", "monto": 20000,
     "evento": "inicial", "total_plan": 300000}
  ]
}
```

`evento` ∈ `inicial | cuota | saldo | completado` (un pago que completa el plan lleva
`completado`).

Lado ventas:

- Modelos nuevos: `PlanPago(referencia unique, tipo, estado, payer_email,
  telefono_o_correo, descripcion, total_plan, total_pagado, venta FK null, apartado
  FK null, creado, actualizado)` y `PagoPlan(plan FK, referencia_pago, monto,
  numero_cuota null, metodo, fecha)`. `unique_together (plan, referencia_pago)` para
  idempotencia.
- Handler:
  - Si existe una `Venta` con `referencia_bold == referencia_pago` (el webhook real de
    Bold llegó antes): marcarla `estado=CANCELADA`, `oculta=True`, `nota='Reemplazada
    por evento de planes'`, y devolver su stock si lo descontó.
  - Ítems `contado`: crear Venta + VentaItem igual que `BoldWebhookView` (extraer la
    creación a un helper reutilizable en `bold_integration/services.py`);
    `referencia_bold = f"{referencia_pago}-{i}"`.
  - `cuotas` + `inicial`: match de producto con `buscar_match_completo`; crear
    `Venta(precio_venta=total_plan, es_separado=True, referencia_bold=plan_ref,
    canal=WEB_BOLD, nombre_producto_bold_raw=descripcion, estado=REGISTRADA o
    PENDIENTE_REVISION si no hay match)`, `VentaItem`, restar stock; `PlanPago` +
    `PagoPlan(monto)`.
  - `cuotas` + `cuota|completado`: `PagoPlan`; `total_pagado += monto`; si
    `completado` → `venta.es_separado=False`.
  - `reserva` + `inicial`: `crear_apartado(telefono_o_correo, monto, vendedor=usuario
    de sistema 'web' (crear si no existe, `settings.PLANES_SYSTEM_USERNAME`),
    nota=descripcion)`; `PlanPago`.
  - `reserva` + `saldo|cuota`: `registrar_abono`. `completado`: `completar_apartado`
    con el `ProductoVariante` del match y `precio_venta=total_plan`.
- `BoldWebhookView`: antes de crear la Venta, si `PagoPlan.objects.filter(referencia_pago=referencia).exists()`
  → responder `duplicado_ignorado` (el evento de planes ya lo registró).
- Vista mínima en la UI de ventas: lista de `PlanPago` con estado y pagos (reusar
  el patrón de `/apartados/`). Migraciones normales de Django (esta app sí las usa).

## 8. Despliegue

Orden obligatorio: (1) SQL de §3 en `hc-postgres`; (2) FastAPI; (3) Django; (4)
frontend-v2; (5) ventas. Cada uno con `docker build -t hc-<svc>:candidate-cuotas .`,
verificación en contenedor desechable y `bash /root/deploy_hc.sh hc-<svc> promote
candidate-cuotas`. Antes de promover, `git fetch` y confirmar que `main`/`master`
incluye lo que corre en producción. Variables de entorno nuevas en
`/root/hc/hc-django.env`: `VENTAS_PLANES_WEBHOOK_URL`, `VENTAS_PLANES_WEBHOOK_SECRET`;
en el `.env` de ventas: `PLANES_WEBHOOK_SECRET`, `PLANES_SYSTEM_USERNAME=web`.
