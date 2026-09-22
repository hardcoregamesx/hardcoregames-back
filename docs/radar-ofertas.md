# Radar de ofertas de tiendas digitales

Fase 0 — recoleccion de datos. Verificado el 2026-09-21.

El radar revisa a diario las ofertas de las tiendas digitales en las regiones donde se
compra, les pone al lado el precio de la tienda colombiana y calcula el margen. **No publica
nada y no toca el catalogo.** Su unico trabajo es responder, con datos reales, si el negocio
de vender sobre pedido vale la pena.

## La regla de negocio

```
precio_venta  = precio_colombia x 0,80        (el cliente ahorra 20%)
margen        = precio_venta - costo_en_la_region_mas_barata
viable si       margen >= 20.000 COP
```

Los tres numeros (`0,80`, `20.000`, y el descuento minimo del 10%) se editan en el admin, en
**Parametros del radar**. No hace falta tocar codigo para moverlos.

El precio de Colombia que se usa como ancla es **el vigente**, no el de lista: si el juego
tambien esta en oferta en Colombia, el cliente puede comprarlo alla y esa es la comparacion
honesta.

## Regiones

| Region | Moneda | Papel |
|---|---|---|
| CO | COP | Referencia. Es el precio contra el que compara el cliente. |
| TR | TRY | Compra. Fuerte en Xbox. |
| IN | INR | Compra. La mas barata de forma consistente. |
| SA | SAR | Compra. Ojo con el catalogo (ver abajo). |
| US | USD | Compra. Unica fuente de codigos. |

**Nintendo no esta y no va a estar**: no existe eShop en Turquia, Arabia Saudita ni India.
Solo en USA, y ahi no hay diferencia aprovechable.

## Las dos trampas que el codigo ya cubre

**1. Juegos que se ven pero no se pueden comprar.** En Arabia Saudita varios titulos M-rated
aparecen listados y con precio, pero su bloque de disponibilidad no incluye la accion
`Purchase`. Si se cuentan, el comparador muestra oportunidades que no se pueden pagar. El
cliente exige `'Purchase' in Actions` y descarta el resto (`PrecioRegional.comprable`).

**2. Promociones sin fecha de fin.** `displaycatalog` usa el ano 9998 para decir "no vence".
Se convierte a vacio, o la landing mostraria un contador regresivo absurdo.

## Comandos

```bash
# Tasas de cambio. Correr antes del radar.
docker exec hc-django python manage.py radar_tasas

# Radar de Xbox. Una vez al dia.
docker exec hc-django python manage.py radar_xbox

# Ver lo que hay, sin escribir nada.
docker exec hc-django python manage.py radar_reporte --top 40
docker exec hc-django python manage.py radar_reporte --min-resenas 20   # solo lo que tiene demanda
```

`radar_xbox --dry-run` consulta las tiendas y muestra el resumen sin escribir en la base.

### Cron sugerido

```
0 6 * * *  docker exec hc-django python manage.py radar_tasas  >> /opt/hardcoregames/radar.log 2>&1
15 6 * * * docker exec hc-django python manage.py radar_xbox   >> /opt/hardcoregames/radar.log 2>&1
```

## El dolar de saldo no es el dolar de mercado

Esta es la pieza que mas cambia los margenes, y conviene entenderla.

El negocio **no compra dolares** para gastarlos en la tienda: compra **saldo**, en forma de
gift cards, y ese saldo se consigue con descuento en buysellvouchers.com. Una tarjeta Xbox de
1 USD se paga alrededor de 0,91 USD. Ese 9% es margen que la TRM no ve.

Y el descuento **no es el mismo en las dos tiendas**. Medido el 21/09/2026:

| Tienda | 1 USD de saldo cuesta | Descuento |
|---|---|---|
| Xbox | 0,910 USD | 9,0% |
| PlayStation | 0,930 USD | 7,0% |

Por eso el costo se compone de dos factores, cada uno con su propia fuente:

```
pesos por dolar de saldo = factor_de_la_tienda  x  TasaCambio['USD']
                           (se lee a diario)        (lo que cuesta un dolar de verdad)
```

El **factor** vive en *Tasas por tienda* y lo actualiza `radar_tasas` todos los dias. El
**dolar de verdad** vive en *Tasas de cambio* y es manual: se siembra con la TRM, pero hay que
editarlo con lo que de verdad cuesta conseguir divisa. Las dos casillas tienen un interruptor
**manual** que congela el valor si se prefiere fijarlo a mano.

Se toma la **mediana de las tres ofertas mas baratas**, no el minimo absoluto: la oferta mas
barata suele ser de un vendedor con una unidad y mala reputacion, y fijar precios de venta con
ella daria un margen que no existe.

Si buysellvouchers falla, se avisa y **se conserva el valor del dia anterior**. Una tasa de
ayer es mucho mejor que ninguna.

**A futuro:** buysellvouchers tiene una API oficial (hub.buysellvouchers.com/giftcard-api/)
con catalogo en vivo, que es el camino correcto. Las llaves solo se dan a compradores ya
registrados y previa revision, asi que hay que solicitarla. Mientras tanto se lee la pagina
publica del listado, que su robots.txt permite (solo bloquea URLs con parametros) y que sirve
los precios en el HTML sin necesidad de JavaScript. Una lectura al dia, con User-Agent
identificado.

Las demas monedas se actualizan solas. El rial saudi esta anclado al dolar a 3,75 desde 1986;
no cambia.

## Cuando se rompa

Estos endpoints **no estan documentados por Microsoft** y no tienen contrato de estabilidad.
Van a cambiar. Senales de que paso:

- `radar_xbox` sale con codigo distinto de cero y escribe el error en **Ejecuciones del radar**.
- Encuentra cero ofertas. Eso nunca es un resultado real: la tienda siempre tiene ofertas.
- Los precios dejan de moverse durante varios dias.

**Un radar roto en silencio es peor que no tener radar**, porque muestra precios viejos y hace
vender a perdida. Por eso el comando falla ruidosamente en vez de guardar una corrida vacia.

### Los dos endpoints

**Listado de ofertas** — `POST https://emerald.xboxservices.com/xboxcomfd/browse?locale=<locale>`

- El mercado lo fija `locale`, **no** un parametro `market`.
- Cabecera `X-MS-API-Version: 1.1` obligatoria (con `1.0` responde 405; sin ella, 400).
- `Filters` va en base64 de un JSON. El filtro nativo `Price=OnSale` **solo funciona en
  `en-US`**; en los demas mercados se ignora. Por eso se ordena por `DiscountPercentage desc`
  y se corta al llegar al 10%, que es el piso que lista Microsoft. Verificado que las dos vias
  dan el mismo conjunto en `en-US` (957 ofertas).
- La paginacion va con `encodedCT`, que se reinyecta en `EncodedCT`.

**Precio por producto** — `GET https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds=...&market=CO&languages=es-co`

- Sin autenticacion. Lotes de 20 ids.
- El `bigId` es **global**: el mismo identificador sirve en todos los mercados. Es lo que hace
  a Xbox la tienda facil de comparar entre regiones.

Si el listado deja de responder, la forma de recuperar el formato es abrir
`xbox.com/es-co/games/browse`, mirar las peticiones de red del navegador y copiar el cuerpo
que envia la pagina.

## PlayStation

Sony **no tiene identificador global**: el SKU cambia por zona. Eso manda en el diseno.

- **Colombia y USA comparten zona** (prefijo `UP`): cruzan por SKU directo. Medido: 90%.
- **Turquia es otra zona** (prefijo `EP`): cruza al 21% por SKU. Sumando el titulo
  normalizado se llega al **70%**.
- El 30% que no cruza son, casi siempre, juegos que Colombia no tiene en oferta. Sin precio
  de referencia no hay margen que calcular, asi que se omiten.

La tienda colombiana de PS **cotiza en dolares**, no en pesos. El precio de referencia se
pasa a pesos con el dolar de mercado (lo que pagaria el cliente comprando el solo), mientras
que el costo usa el dolar de saldo de PSN, que es mas barato.

La rejilla de ofertas no trae la fecha de fin: hay que pedirla producto a producto. Como
cuesta una peticion por juego, solo se pide para los mas rentables (`--max-detalles`, 400 por
defecto). Sin fecha de fin no hay contador ni retirada automatica.

**Cuando Sony rote el hash** de la consulta pre-aprobada, el radar respondera que la consulta
fue rechazada y lo dira con esas palabras. Para recapturarlo: abrir store.playstation.com,
mirar las peticiones de red del navegador y copiar el `sha256Hash` de `categoryGridRetrieve`.
Los hashes viven en `radar/tiendas/playstation.py`.

## Por que aqui no hay migraciones de Django

**Este proyecto no usa `migrate` en ningun app, y no es una preferencia: no puede.** El app
`users` declara una relacion hacia `auth.User` (que si tiene migraciones) sin tener
migraciones propias, y Django se niega a construir el grafo de migraciones en esa situacion.
Cualquier `migrate`, aunque sea de un app nuevo y aislado, falla con:

```
...to a model in an app with migrations (e.g. contrib.auth) in an app with no migrations
```

Por eso todos los modelos del radar son `managed = False` y el esquema se crea con SQL
directo desde **`radar/sql/2026-09-radar.sql`**, que es la fuente de verdad. Es el mismo
patron de `products/sql/`, `membership/sql/` y las tablas de `rewards`.

```bash
docker exec -i hc-postgres psql -U hardcoregames -d hardcoregames -v ON_ERROR_STOP=1   < /opt/hardcoregames/repos/django/radar/sql/2026-09-radar.sql
```

Si se agrega un campo a un modelo del radar, hay que agregar la columna en ese SQL a mano.
No hay `makemigrations` que lo haga.

Aparte, esta app tampoco tiene relaciones formales hacia `products`: el vinculo con el
catalogo propio es un entero suelto (`JuegoDetectado.producto_existente_id`) y el cruce se
hace por titulo normalizado.

## Despliegue

```bash
git -C /opt/hardcoregames/repos/django pull --ff-only
bash /opt/hardcoregames/repos/django/deploy/deploy-radar-fase0.sh
```

El script es idempotente y deja la migracion aplicada, las tasas sembradas, la primera
corrida hecha y el cron diario instalado. Rollback: `bash /root/deploy_hc.sh hc-django rollback`.
