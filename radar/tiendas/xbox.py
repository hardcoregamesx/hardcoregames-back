# -*- coding: utf-8 -*-
"""Cliente de la tienda Xbox.

Dos endpoints, ambos sin autenticacion y ambos NO documentados por Microsoft
(ver docs/radar-ofertas.md, seccion de riesgos):

1. `emerald.xboxservices.com/xboxcomfd/browse` -- el que usa xbox.com. Lista las
   ofertas de un mercado. El mercado lo fija `locale`, NO un parametro `market`.
   No existe un filtro de "solo ofertas" que funcione fuera de en-US, pero
   ordenar por descuento descendente y parar al llegar a 0% enumera exactamente
   el mismo conjunto (verificado: en-US da 957 por las dos vias).

2. `displaycatalog.mp.microsoft.com/v7.0/products` -- consulta por lote el
   precio de un bigId en cualquier mercado. Se usa para el precio de referencia
   de Colombia, que hace falta aunque el juego no este en oferta alla.

El `bigId` es global: el mismo identificador sirve en todos los mercados. Es la
razon por la que Xbox es la tienda mas facil de comparar entre regiones.
"""
import base64
import json
from datetime import datetime

import requests
from django.utils import timezone

EMERALD_URL = 'https://emerald.xboxservices.com/xboxcomfd/browse'
DISPLAYCATALOG_URL = 'https://displaycatalog.mp.microsoft.com/v7.0/products'

USER_AGENT = 'HardcoreGamesRadar/1.0 (+https://www.hardcoregames.co)'

# Regiones de compra del negocio, mas Colombia como referencia.
# region -> (locale de emerald, locale de displaycatalog)
REGIONES = {
    'CO': ('es-CO', 'es-co'),
    'TR': ('tr-TR', 'tr-tr'),
    'IN': ('en-IN', 'en-in'),
    'SA': ('ar-SA', 'ar-sa'),
    'US': ('en-US', 'en-us'),
}

# Microsoft no lista descuentos por debajo del 10%: es el corte natural.
DESCUENTO_PISO = 10.0

# displaycatalog acepta lotes; 20 es conservador y estable.
LOTE_DISPLAYCATALOG = 20

_FILTRO_OFERTAS = {
    'orderby': {'id': 'orderby', 'choices': [{'id': 'DiscountPercentage desc'}]},
    'Price': {'id': 'Price', 'choices': [{'id': 'OnSale'}]},
}


class ErrorTienda(Exception):
    """Fallo al hablar con la tienda. Se propaga: el radar debe fallar ruidosamente."""


def _filtros_b64():
    crudo = json.dumps(_FILTRO_OFERTAS, separators=(',', ':')).encode('utf-8')
    return base64.b64encode(crudo).decode('ascii')


def _parsear_fecha(valor):
    """Las dos APIs devuelven la fecha en formatos distintos."""
    if not valor:
        return None
    valor = str(valor).strip()
    formatos = ('%m/%d/%Y %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S')
    limpio = valor.replace('Z', '')
    if '.' in limpio and 'T' in limpio:
        limpio = limpio.split('.')[0]
    for fmt in formatos:
        try:
            fecha = datetime.strptime(limpio, fmt)
        except ValueError:
            continue
        # displaycatalog usa el ano 9998 para decir "sin fecha de fin". Dejarlo
        # pasar pondria un contador regresivo absurdo en la landing.
        if fecha.year > 2100:
            return None
        return timezone.make_aware(fecha, timezone.utc)
    return None


def _sesion():
    s = requests.Session()
    s.headers.update({'User-Agent': USER_AGENT})
    return s


def ofertas(region, max_paginas=60, descuento_minimo=DESCUENTO_PISO, sesion=None, log=None):
    """Devuelve la lista de ofertas vigentes de una region.

    Pagina ordenando por descuento descendente y corta cuando el descuento baja
    del minimo pedido, que es justo donde termina el catalogo de ofertas.
    """
    if region not in REGIONES:
        raise ErrorTienda('Region desconocida: %s' % region)

    locale = REGIONES[region][0]
    sesion = sesion or _sesion()
    filtros = _filtros_b64()
    continuacion = None
    encontradas = []
    vistos = set()

    for pagina in range(max_paginas):
        cuerpo = {
            'Filters': filtros,
            'ReturnFilters': False,
            'ChannelKeyToBeUsedInResponse': 'K',
            'EncodedCT': continuacion,
            'ChannelId': None,
        }
        try:
            r = sesion.post(
                EMERALD_URL,
                params={'locale': locale},
                headers={
                    'content-type': 'application/json',
                    'X-MS-API-Version': '1.1',
                    'ms-cv': 'hcradar',
                },
                data=json.dumps(cuerpo),
                timeout=30,
            )
        except requests.RequestException as exc:
            raise ErrorTienda('Xbox %s: fallo de red en la pagina %s: %s' % (region, pagina + 1, exc))

        if r.status_code != 200:
            raise ErrorTienda('Xbox %s: HTTP %s en la pagina %s' % (region, r.status_code, pagina + 1))

        try:
            datos = r.json()
        except ValueError:
            raise ErrorTienda('Xbox %s: respuesta no es JSON en la pagina %s' % (region, pagina + 1))

        canal = (datos.get('channels') or {}).get('K') or {}
        fichas = {p.get('productId'): p for p in (datos.get('productSummaries') or [])}
        disponibilidades = datos.get('availabilitySummaries') or []

        if not disponibilidades:
            break

        corto = False
        for disp in disponibilidades:
            precio = disp.get('price') or {}
            descuento = precio.get('discountPercentage') or 0.0
            if descuento < descuento_minimo:
                corto = True
                break

            big_id = disp.get('productId')
            if not big_id or big_id in vistos:
                continue
            vistos.add(big_id)

            ficha = fichas.get(big_id) or {}
            encontradas.append({
                'id_externo': big_id,
                'titulo': (ficha.get('title') or '')[:300],
                'descripcion': ficha.get('shortDescription') or ficha.get('description') or '',
                'imagen': _imagen(ficha),
                'generos': ', '.join(ficha.get('categories') or [])[:300],
                'clasificacion': ((ficha.get('contentRating') or {}).get('rating') or '')[:80],
                'plataformas': ', '.join(ficha.get('availableOn') or [])[:160],
                'desarrollador': (ficha.get('developerName') or ficha.get('publisherName') or '')[:200],
                'rating': ficha.get('averageRating') or 0.0,
                'rating_conteo': ficha.get('ratingCount') or 0,
                'moneda': precio.get('currency') or '',
                'precio_lista': precio.get('msrp'),
                'precio_oferta': precio.get('listPrice'),
                'descuento_pct': descuento,
                'comprable': 'Purchase' in (disp.get('actions') or []),
                'fecha_fin': _parsear_fecha(disp.get('endDateUtc') or precio.get('endDateUtc')),
            })

        if log:
            log('  %s pagina %s: %s ofertas acumuladas' % (region, pagina + 1, len(encontradas)))

        continuacion = canal.get('encodedCT')
        if corto or not continuacion:
            break

    return encontradas


def _imagen(ficha):
    imagenes = ficha.get('images') or {}
    for clave in ('boxArt', 'poster', 'superHeroArt', 'titledHeroArt'):
        img = imagenes.get(clave) or {}
        url = img.get('url')
        if url:
            return ('https:' + url if url.startswith('//') else url)[:700]
    return ''


def precios(big_ids, region, sesion=None, log=None):
    """Precio de una lista de bigIds en un mercado, via displaycatalog.

    Devuelve {big_id: {...}}. Solo se considera valido un precio cuyo bloque de
    disponibilidad incluya la accion `Purchase`: hay juegos que aparecen con
    precio pero no se pueden comprar en esa tienda (M-rated en Arabia Saudita,
    por ejemplo) y contarlos seria una oportunidad fantasma.
    """
    if region not in REGIONES:
        raise ErrorTienda('Region desconocida: %s' % region)

    idioma = REGIONES[region][1]
    sesion = sesion or _sesion()
    resultado = {}
    ids = [i for i in dict.fromkeys(big_ids) if i]

    for inicio in range(0, len(ids), LOTE_DISPLAYCATALOG):
        lote = ids[inicio:inicio + LOTE_DISPLAYCATALOG]
        try:
            r = sesion.get(
                DISPLAYCATALOG_URL,
                params={
                    'bigIds': ','.join(lote),
                    'market': region,
                    'languages': idioma,
                    'MS-CV': 'hcradar',
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise ErrorTienda('Xbox %s: fallo de red consultando precios: %s' % (region, exc))

        if r.status_code != 200:
            raise ErrorTienda('Xbox %s: HTTP %s consultando precios' % (region, r.status_code))

        try:
            datos = r.json()
        except ValueError:
            raise ErrorTienda('Xbox %s: respuesta no es JSON consultando precios' % region)

        for producto in (datos.get('Products') or []):
            big_id = producto.get('ProductId')
            info = _mejor_disponibilidad(producto)
            if big_id and info:
                resultado[big_id] = info

        if log:
            log('  %s precios: %s/%s consultados' % (region, min(inicio + LOTE_DISPLAYCATALOG, len(ids)), len(ids)))

    return resultado


def _mejor_disponibilidad(producto):
    """Del arbol de displaycatalog saca el precio comprable mas barato."""
    mejor = None
    for sku in (producto.get('DisplaySkuAvailabilities') or []):
        for disp in (sku.get('Availabilities') or []):
            acciones = disp.get('Actions') or []
            if 'Purchase' not in acciones:
                continue
            datos_precio = ((disp.get('OrderManagementData') or {}).get('Price') or {})
            lista = datos_precio.get('ListPrice')
            msrp = datos_precio.get('MSRP')
            if lista is None and msrp is None:
                continue
            fin = _parsear_fecha((disp.get('Conditions') or {}).get('EndDate'))
            candidato = {
                'moneda': datos_precio.get('CurrencyCode') or '',
                'precio_lista': msrp,
                'precio_oferta': lista,
                'comprable': True,
                'fecha_fin': fin,
            }
            valor = lista if lista is not None else msrp
            if mejor is None or (valor is not None and valor < (mejor['precio_oferta'] or mejor['precio_lista'])):
                mejor = candidato
    return mejor
