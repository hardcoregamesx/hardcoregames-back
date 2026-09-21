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

## El dolar es manual, a proposito

`TasaCambio` tiene una casilla **manual**. El dolar viene marcado asi porque se consigue por
debajo de la TRM, y ese descuento es margen que ninguna API conoce. `radar_tasas` **no lo
sobrescribe**: hay que editarlo en el admin con el costo real de conseguir divisa. Las demas
monedas se actualizan solas.

El rial saudi esta anclado al dolar a 3,75 desde 1986; no cambia.

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

## PlayStation, cuando llegue su turno

PlayStation no usa un identificador global: el SKU **cambia en cada region**. La llave que los
une es el `concept.id`, y el mapa `concept -> SKU por region` hay que construirlo y guardarlo
juego por juego. Por eso Xbox va primero.

Ademas, Sony dolarizo Latinoamerica: la tienda colombiana cotiza en dolares al mismo precio
que la de USA. Comprar PS en USA ya no da margen de precio, solo el de la divisa.

## Por que esta app no toca `products`

La app `products` **no tiene migraciones** — su esquema se administra por fuera de Django.
Una relacion formal hacia sus modelos haria imposible migrar esta app. Por eso el vinculo con
el catalogo propio es un entero suelto (`JuegoDetectado.producto_existente_id`) y el cruce se
hace por titulo normalizado. Nunca correr `migrate` sin nombrar la app:

```bash
docker exec hc-django python manage.py migrate radar
```
