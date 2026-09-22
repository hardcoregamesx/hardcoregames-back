# -*- coding: utf-8 -*-
"""Cliente de la PlayStation Store.

Mas incomodo que Xbox, y conviene saber por que antes de tocarlo.

Sony no tiene un identificador global: el SKU cambia por zona. Colombia y USA
comparten zona (prefijo `UP`), asi que ahi el cruce es directo -- medido: 90%
de las ofertas de USA se encuentran en Colombia por SKU. Turquia es otra zona
(prefijo `EP`) y solo cruza un 21% por SKU; cruzando ademas por titulo
normalizado se llega al 70%. El 30% restante son, en su mayoria, juegos que
Colombia no tiene en oferta: sin precio de referencia no hay margen que
calcular, asi que se dejan fuera.

El endpoint solo acepta consultas pre-aprobadas: el `sha256Hash` de abajo es
parte del contrato. Sony lo rota con cada despliegue de su web; cuando eso pase
el radar empezara a responder `PersistedQueryNotFound` y habra que recapturarlo
abriendo store.playstation.com y mirando las peticiones de red del navegador.
Ver docs/radar-ofertas.md.
"""
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone as tz_utc
from decimal import Decimal, InvalidOperation

import requests
from django.utils import timezone

URL = 'https://web.np.playstation.com/api/graphql/v1/op'

# Consultas pre-aprobadas. Si Sony las rota, aqui es donde se actualizan.
HASH_GRID = '9845afc0dbaab4965f6563fffc703f588c8e76792000e8610843b8d3ee9c4c09'
HASH_PRODUCTO = '1f0ca607e170abbfb7d67bd76c9bbc97f21fe2e807be49e5fe764e14566cb605'
CATEGORIA_OFERTAS = '3f772501-f6f8-49b7-abac-874a88ca4897'

# El locale es lo unico que decide el mercado, igual que en Xbox.
REGIONES = {
    'CO': 'es-CO',
    'US': 'en-US',
    'TR': 'tr-TR',
}

# Que cuenta como "un juego". La rejilla de ofertas mezcla juegos con DLC,
# pases de temporada, monedas virtuales, skins y mapas -- mas de un tercio del
# listado. Dos motivos para filtrarlos: no son lo que se vende, y al cruzar por
# titulo un DLC turco barato podia emparejarse con el juego completo
# colombiano, inventando un margen que no existe.
#
# Sony devuelve esta etiqueta TRADUCIDA por mercado, asi que hay una lista por
# idioma. Si aparece una etiqueta nueva, el juego se omite y se avisa: es mas
# seguro perder una oferta que publicar un DLC como si fuera el juego.
CLASES_JUEGO = {
    'es-CO': {'Juego completo', 'Paquete de juego', 'Edicion premium', 'Edición premium'},
    'en-US': {'Full Game', 'Game Bundle', 'Premium Edition'},
    'tr-TR': {'Tam Sürüm Oyun', 'Oyun Paketi', 'Premium Sürüm'},
}

USER_AGENT = 'HardcoreGamesRadar/1.0 (+https://www.hardcoregames.co)'
TIMEOUT = 90
PAGINA = 1000          # tope que acepta el endpoint
INTENTOS = 3
ESPERA_BASE = 3


class ErrorTienda(Exception):
    """Fallo al hablar con la tienda. Se propaga: el radar debe fallar ruidosamente."""


def _sesion():
    s = requests.Session()
    s.headers.update({'User-Agent': USER_AGENT, 'content-type': 'application/json'})
    return s


def _pedir(sesion, locale, operacion, hash_consulta, variables, descripcion, log=None):
    parametros = {
        'operationName': operacion,
        'variables': json.dumps(variables, separators=(',', ':')),
        'extensions': json.dumps(
            {'persistedQuery': {'version': 1, 'sha256Hash': hash_consulta}}, separators=(',', ':')),
    }
    ultimo = None
    for intento in range(1, INTENTOS + 1):
        try:
            r = sesion.get(URL, params=parametros,
                           headers={'x-psn-store-locale-override': locale}, timeout=TIMEOUT)
        except (requests.Timeout, requests.ConnectionError) as exc:
            ultimo = exc
            if intento < INTENTOS:
                espera = ESPERA_BASE * (2 ** (intento - 1))
                if log:
                    log('  %s: fallo de red (intento %s), reintento en %ss' % (descripcion, intento, espera))
                time.sleep(espera)
                continue
            raise ErrorTienda('%s: la red fallo %s veces (%s)' % (descripcion, INTENTOS, ultimo))

        if r.status_code != 200:
            raise ErrorTienda('%s: HTTP %s' % (descripcion, r.status_code))
        try:
            datos = r.json()
        except ValueError:
            raise ErrorTienda('%s: respuesta no es JSON' % descripcion)

        if 'PersistedQueryNotFound' in r.text or datos.get('errors'):
            # Es LA senal de que Sony roto el hash. Merece un mensaje propio:
            # de otro modo se confunde con un fallo pasajero y se pierde tiempo.
            raise ErrorTienda(
                '%s: Sony rechazo la consulta. Lo mas probable es que rotara el sha256Hash; '
                'hay que recapturarlo (ver docs/radar-ofertas.md).' % descripcion)
        return datos
    raise ErrorTienda('%s: sin respuesta' % descripcion)


# --- precios -----------------------------------------------------------------
# Vienen como texto ya formateado y cada mercado usa su convencion:
#   "US$39.99"  "$19.99"  "1.541,00 TL"  "704,70 TL"
_MONEDAS = (('TL', 'TRY'), ('US$', 'USD'), ('$', 'USD'))


def _parsear_precio(texto):
    """Devuelve (Decimal, moneda) o (None, '')."""
    if not texto:
        return None, ''
    texto = str(texto).strip()
    moneda = ''
    for marca, codigo in _MONEDAS:
        if marca in texto:
            moneda = codigo
            break
    numero = re.sub(r'[^0-9.,]', '', texto)
    if not numero:
        return None, moneda
    # Si hay coma y punto, el ultimo que aparece es el separador decimal.
    if ',' in numero and '.' in numero:
        if numero.rfind(',') > numero.rfind('.'):
            numero = numero.replace('.', '').replace(',', '.')
        else:
            numero = numero.replace(',', '')
    elif ',' in numero:
        # "704,70" es decimal; "1,541" en un precio turco seria raro.
        entero, _, resto = numero.partition(',')
        numero = '%s.%s' % (entero, resto) if len(resto) <= 2 else entero + resto
    try:
        return Decimal(numero), moneda
    except InvalidOperation:
        return None, moneda


def normalizar_titulo(titulo):
    """Para cruzar el mismo juego entre mercados cuando el SKU no coincide."""
    t = (titulo or '').lower()
    for simbolo in ('™', '®', '©'):
        t = t.replace(simbolo, '')
    t = re.sub(r'\b(ps4|ps5|ve|and|edition|edicion|edición|surumu|sürümü|'
               r'paketi|bundle|pack|standard|estándar)\b', ' ', t)
    t = re.sub(r'[^a-z0-9]+', ' ', t)
    return ' '.join(t.split())


def ofertas(region, sesion=None, log=None, tope=8000):
    """Todas las ofertas vigentes de un mercado."""
    if region not in REGIONES:
        raise ErrorTienda('Region desconocida: %s' % region)
    locale = REGIONES[region]
    sesion = sesion or _sesion()

    encontradas, offset = [], 0
    descartadas = Counter()
    while offset < tope:
        datos = _pedir(
            sesion, locale, 'categoryGridRetrieve', HASH_GRID,
            {'id': CATEGORIA_OFERTAS, 'pageArgs': {'size': PAGINA, 'offset': offset},
             'sortBy': None, 'filterBy': [], 'facetOptions': []},
            'PlayStation %s pagina %s' % (region, offset // PAGINA + 1), log=log)

        grid = (datos.get('data') or {}).get('categoryGridRetrieve') or {}
        lote = grid.get('products') or []
        if not lote:
            break

        permitidas = CLASES_JUEGO.get(locale, set())
        for prod in lote:
            clase = prod.get('localizedStoreDisplayClassification') or ''
            if permitidas and clase not in permitidas:
                descartadas[clase] += 1
                continue
            precio = prod.get('price') or {}
            lista, moneda = _parsear_precio(precio.get('basePrice'))
            oferta, _ = _parsear_precio(precio.get('discountedPrice'))
            if oferta is None:
                continue
            descuento = re.sub(r'[^0-9]', '', precio.get('discountText') or '') or '0'
            encontradas.append({
                'id_externo': prod.get('id'),
                'clase': clase,
                'titulo': (prod.get('name') or '')[:300],
                'titulo_normalizado': normalizar_titulo(prod.get('name')),
                'imagen': _imagen(prod),
                'plataformas': ', '.join(prod.get('platforms') or [])[:160],
                'moneda': moneda,
                'precio_lista': lista,
                'precio_oferta': oferta,
                'descuento_pct': Decimal(descuento),
                'comprable': True,
            })

        if len(lote) < PAGINA:
            break
        offset += PAGINA

    if log:
        log('  %s: %s juegos (descartados %s DLC, pases y similares)'
            % (region, len(encontradas), sum(descartadas.values())))
    return encontradas


def _imagen(prod):
    preferidas = ('MASTER', 'GAMEHUB_COVER_ART', 'PORTRAIT_BANNER', 'SIXTEEN_BY_NINE_BANNER')
    medios = prod.get('media') or []
    for rol in preferidas:
        for m in medios:
            if m.get('role') == rol and m.get('url'):
                return m['url'][:700]
    for m in medios:
        if m.get('url'):
            return m['url'][:700]
    return ''


def detalle(sku, region, sesion=None, log=None):
    """Precio numerico y fecha de fin de la promocion de un producto.

    La rejilla no trae `endTime`, y sin fecha de fin la landing no puede
    mostrar el contador ni retirar la oferta sola. Cuesta una peticion por
    producto, asi que solo se pide para lo que de verdad va a publicarse.
    """
    if region not in REGIONES:
        raise ErrorTienda('Region desconocida: %s' % region)
    sesion = sesion or _sesion()
    datos = _pedir(sesion, REGIONES[region], 'productRetrieveForCtasWithPrice', HASH_PRODUCTO,
                   {'productId': sku}, 'PlayStation %s detalle' % region, log=log)

    producto = (datos.get('data') or {}).get('productRetrieve') or {}
    for cta in (producto.get('webctas') or []):
        # El CTA de PS Plus trae descuento 0 y regalaria el juego si se lee
        # como precio: solo sirve el de compra.
        if cta.get('type') not in (None, 'ADD_TO_CART', 'PRE_ORDER'):
            continue
        precio = cta.get('price') or {}
        if not precio.get('discountedValue'):
            continue
        fin = None
        if precio.get('endTime'):
            try:
                fin = datetime.fromtimestamp(int(precio['endTime']) / 1000, tz_utc.utc)
            except (ValueError, TypeError, OSError):
                fin = None
        return {
            'moneda': precio.get('currencyCode') or '',
            'fecha_fin': fin,
            'concepto': ((producto.get('concept') or {}).get('id')),
        }
    return {'moneda': '', 'fecha_fin': None, 'concepto': None}
