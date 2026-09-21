# -*- coding: utf-8 -*-
"""Cuanto cuesta de verdad un dolar de saldo, segun buysellvouchers.com.

El radar no puede calcular el margen real con la TRM: el dueno no compra
dolares, compra **saldo de tienda** en forma de gift cards, y ese saldo se
consigue con descuento. Una tarjeta Xbox de 1 USD se paga ~0,91 USD; esa
diferencia es margen que ninguna API de divisas conoce.

Y el descuento NO es el mismo en las dos tiendas: el dolar de Xbox y el de PSN
se cotizan por separado, por eso cada tienda tiene su propia tasa.

Sobre el origen de los datos: buysellvouchers tiene una API oficial
(hub.buysellvouchers.com/giftcard-api/) que es el camino correcto a futuro,
pero las llaves solo se dan a compradores ya registrados y previa revision.
Mientras tanto se lee la pagina publica del listado, que su robots.txt permite
(solo bloquea URLs con parametros) y que sirve los precios en el HTML, sin
JavaScript. Una lectura al dia, identificandose con un User-Agent honesto.
"""
import re
from decimal import Decimal, InvalidOperation

import requests
from bs4 import BeautifulSoup

BASE = 'https://www.buysellvouchers.com'

# Listados publicos por tienda. Sin parametros en la URL: el robots.txt los
# bloquea, y ademas la primera pagina ya trae las ofertas mas baratas.
RUTAS = {
    'XBOX': '/en/products/list/Gift_cards-Xbox/',
    'PS': '/en/products/list/Gift_cards-PlayStation_network_aka_psn/',
}

USER_AGENT = 'HardcoreGamesRadar/1.0 (+https://www.hardcoregames.co)'
TIMEOUT = 45

# Como se reconoce una tarjeta de Estados Unidos en el titulo o en el cuerpo de
# la tarjeta. Se exige region explicita: mezclar una tarjeta turca con una
# gringa daria un "dolar" que no existe.
PATRON_USA = re.compile(r'\bUSA\b|\bUS\b|United States', re.IGNORECASE)
PATRON_MONEDA = re.compile(r'\bUSD\b|\$', re.IGNORECASE)

# "1.00" = valor nominal (sin simbolo, siempre con dos decimales).
# "$0.91" = lo que se paga. Los enteros sueltos de la tarjeta son stock y
# reputacion del vendedor, no precios: por eso el nominal exige decimales.
PATRON_NOMINAL = re.compile(r'^\d+[.,]\d{2}$')
PATRON_PRECIO = re.compile(r'^\$\s*\d+(?:[.,]\d{1,3})?$')
PATRON_NUMERO = re.compile(r'^\$?\s*(\d+(?:[.,]\d{1,3})?)$')


class ErrorVouchers(Exception):
    """No se pudo averiguar el precio del dolar. El radar sigue con la tasa anterior."""


def _a_decimal(texto):
    m = PATRON_NUMERO.match(texto.strip())
    if not m:
        return None
    try:
        return Decimal(m.group(1).replace(',', '.'))
    except InvalidOperation:
        return None


def _tarjeta_de(titulo_nodo):
    """Devuelve el contenedor de ESA oferta, y solo de esa.

    El precio no vive junto al titulo sino en un hermano, asi que hay que subir.
    La regla es subir mientras el contenedor siga teniendo un unico <h3> y
    quedarse con el ultimo: ese es el trozo mas grande que todavia describe una
    sola oferta. Un nivel mas y ya se mezclan dos, lo que daria precios cruzados
    -- un "dolar barato" que en realidad es el nominal de otra tarjeta.
    """
    mejor = None
    nodo = titulo_nodo
    for _ in range(8):
        nodo = nodo.parent
        if nodo is None:
            break
        if len(nodo.find_all('h3')) != 1:
            break
        mejor = nodo
    return mejor


def ofertas_usd(tienda, sesion=None, log=None):
    """Ofertas de tarjetas en dolares de esa tienda, con su factor de descuento.

    Devuelve una lista de dicts: {titulo, nominal, precio, factor}, donde
    `factor` es cuantos dolares cuesta un dolar de saldo (0.91 = 9% de
    descuento).
    """
    if tienda not in RUTAS:
        raise ErrorVouchers('Tienda desconocida: %s' % tienda)

    sesion = sesion or requests.Session()
    sesion.headers.update({'User-Agent': USER_AGENT})
    url = BASE + RUTAS[tienda]

    try:
        r = sesion.get(url, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ErrorVouchers('No se pudo leer %s: %s' % (url, exc))
    if r.status_code != 200:
        raise ErrorVouchers('%s respondio HTTP %s' % (url, r.status_code))

    sopa = BeautifulSoup(r.text, 'html.parser')
    encontradas = []

    for titulo_nodo in sopa.find_all('h3'):
        titulo = titulo_nodo.get_text(strip=True)
        # En la pagina tambien hay <h3> de la barra de filtros y del texto SEO.
        if 'gift card' not in titulo.lower() and 'psn' not in titulo.lower():
            continue
        tarjeta = _tarjeta_de(titulo_nodo)
        if tarjeta is None:
            continue
        cuerpo = tarjeta.get_text(' ', strip=True)

        if not PATRON_USA.search(titulo) and not PATRON_USA.search(cuerpo):
            continue
        if not PATRON_MONEDA.search(titulo) and 'USD' not in cuerpo:
            continue

        # Cuidado con confundir el valor nominal con otros numeros de la
        # tarjeta: ahi conviven el stock ("2467"), la reputacion del vendedor
        # ("6") y las ventas totales. El nominal siempre viene con dos
        # decimales y sin simbolo ("1.00"); el precio, con simbolo ("$0.91").
        nominal, precio = None, None
        for nodo in tarjeta.find_all(['span', 'div', 'p', 'strong', 'b']):
            texto = nodo.get_text(strip=True)
            if not texto or len(texto) > 12:
                continue
            if PATRON_PRECIO.match(texto):
                valor = _a_decimal(texto)
                if valor and (precio is None or valor < precio):
                    precio = valor
            elif PATRON_NOMINAL.match(texto) and nominal is None:
                nominal = _a_decimal(texto)

        if not nominal or not precio:
            continue
        factor = (precio / nominal).quantize(Decimal('0.000001'))
        # Un factor absurdo es senal de que se cruzaron dos ofertas al leer, no
        # de un chollo. Descartarlo es mas seguro que fijar un precio con el.
        if factor < Decimal('0.5') or factor > Decimal('1.5'):
            continue
        encontradas.append({
            'titulo': titulo, 'nominal': nominal, 'precio': precio, 'factor': factor,
        })

    if log:
        log('  %s: %s ofertas en dolares leidas' % (tienda, len(encontradas)))
    return encontradas


def factor_dolar(tienda, sesion=None, log=None):
    """El mejor precio del dolar de saldo en esa tienda.

    Se toma la **mediana de las tres mejores**, no el minimo absoluto: la oferta
    mas barata suele ser de un vendedor con una unidad y mala reputacion, y
    fijar el precio de venta con ella daria un margen que no existe.
    """
    encontradas = ofertas_usd(tienda, sesion=sesion, log=log)
    if not encontradas:
        raise ErrorVouchers(
            '%s: no se reconocio ninguna oferta en dolares. Probablemente cambio el HTML '
            'del listado (ver docs/radar-ofertas.md).' % tienda)

    mejores = sorted(encontradas, key=lambda o: o['factor'])[:3]
    factor = sorted(o['factor'] for o in mejores)[len(mejores) // 2]
    return {
        'factor': factor,
        'muestras': len(encontradas),
        'usadas': [(o['titulo'], str(o['factor'])) for o in mejores],
    }
