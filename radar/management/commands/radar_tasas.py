# -*- coding: utf-8 -*-
"""Actualiza las tasas de cambio que usa el radar para convertir a pesos."""
from decimal import Decimal, InvalidOperation

import requests
from django.core.management.base import BaseCommand

from radar.models import TasaCambio, TasaTienda
from radar.tiendas import vouchers

# Base USD, gratis y sin llave. Cubre COP, TRY, INR y SAR.
API_TASAS = 'https://open.er-api.com/v6/latest/USD'
# TRM oficial de Colombia. Es el dolar que pagaria el cliente comprando el solo.
API_TRM = 'https://www.datos.gov.co/resource/32sa-8pi3.json?$limit=1&$order=vigenciadesde%20DESC'
# Binance P2P, la misma API publica y sin llave que usa su web. tradeType BUY
# son los anuncios de quien vende USDT por pesos: lo que cuesta comprarlo.
API_BINANCE_P2P = 'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search'

# Si el USDT mas barato se aleja de la TRM mas que esto, el anuncio no es real
# (o la API cambio) y se conserva el dolar del dia anterior.
DESVIO_MAXIMO_USDT = Decimal('0.10')

# Monedas de las regiones de compra del negocio. USD y TRM van aparte.
MONEDAS = ['TRY', 'INR', 'SAR']

NOTAS = {
    'USD': 'Automatico: USDT mas barato de Binance P2P. Con el se paga buysellvouchers.',
    'TRM': 'TRM oficial (datos.gov.co). Precio de referencia de la tienda PS Colombia.',
    'SAR': 'El rial esta anclado al dolar a 3,75 desde 1986.',
}


class Command(BaseCommand):
    help = (
        'Actualiza las tasas de cambio del radar (cuantos pesos vale una unidad de cada '
        'moneda de compra). El dolar (USD) es el USDT mas barato de Binance P2P, que es '
        'con lo que se paga el saldo en buysellvouchers; la TRM se guarda aparte como '
        'dolar de mercado. Las tasas marcadas como manuales NO se tocan.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--forzar-usd', action='store_true',
            help='Actualiza el dolar con Binance aunque este marcado como manual, y lo desmarca.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Muestra las tasas que se guardarian, sin escribir.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        forzar_usd = options['forzar_usd']

        try:
            r = requests.get(API_TASAS, timeout=30)
            r.raise_for_status()
            datos = r.json()
        except (requests.RequestException, ValueError) as exc:
            self.stderr.write(self.style.ERROR('No se pudieron leer las tasas: %s' % exc))
            raise SystemExit(1)

        if datos.get('result') != 'success':
            self.stderr.write(self.style.ERROR('La API de tasas respondio sin exito: %s' % datos.get('result')))
            raise SystemExit(1)

        rates = datos.get('rates') or {}
        cop_por_usd = rates.get('COP')
        if not cop_por_usd:
            self.stderr.write(self.style.ERROR('La API de tasas no trajo COP.'))
            raise SystemExit(1)

        cop_por_usd = Decimal(str(cop_por_usd))
        self.stdout.write('Tasas de %s' % datos.get('time_last_update_utc', 'fecha desconocida'))

        existentes = {t.moneda: t for t in TasaCambio.objects.all()}
        nuevas = {}

        trm = self._trm() or cop_por_usd
        if existentes.get('TRM') and existentes['TRM'].manual:
            self.stdout.write('  TRM = %s COP (manual, sin tocar).' % existentes['TRM'].cop_por_unidad)
        else:
            nuevas['TRM'] = trm
        nuevas['USD'] = self._dolar(existentes.get('USD'), trm, forzar_usd)

        for moneda in MONEDAS:
            actual = existentes.get(moneda)
            por_usd = rates.get(moneda)
            if not por_usd:
                self.stderr.write(self.style.WARNING('  %s: la API no la trajo, se omite.' % moneda))
                continue
            try:
                valor = cop_por_usd / Decimal(str(por_usd))
            except (InvalidOperation, ZeroDivisionError):
                self.stderr.write(self.style.WARNING('  %s: valor invalido, se omite.' % moneda))
                continue
            if actual and actual.manual:
                self.stdout.write('  %s = %s COP (manual, sin tocar).' % (moneda, actual.cop_por_unidad))
                continue
            nuevas[moneda] = valor

        escritas = 0
        for moneda, valor in nuevas.items():
            if valor is None:
                continue
            valor = valor.quantize(Decimal('0.000001'))
            self.stdout.write('  %s = %s COP' % (moneda, valor))
            if not dry_run:
                TasaCambio.objects.update_or_create(
                    moneda=moneda,
                    defaults={
                        'cop_por_unidad': valor,
                        'manual': False,
                        'nota': NOTAS.get(moneda, ''),
                    },
                )
                escritas += 1

        self._dolar_de_saldo(dry_run)

        if dry_run:
            self.stdout.write(self.style.WARNING('Modo --dry-run: no se escribio nada.'))
        else:
            self.stdout.write(self.style.SUCCESS('Tasas actualizadas: %s' % escritas))

    def _dolar_de_saldo(self, dry_run):
        """El dolar de saldo de cada tienda, desde buysellvouchers.

        Si falla se avisa y se sigue con el valor anterior: quedarse con una
        tasa de ayer es mucho mejor que dejar al radar sin ninguna.
        """
        self.stdout.write('Dolar de saldo (buysellvouchers):')
        existentes = TasaTienda.mapa()

        for tienda in ('XBOX', 'PS'):
            actual = existentes.get(tienda)
            if actual and actual.manual:
                self.stdout.write('  %-5s = %s USD (manual, sin tocar)' % (tienda, actual.factor))
                continue
            try:
                resultado = vouchers.factor_dolar(tienda)
            except vouchers.ErrorVouchers as exc:
                anterior = ('se mantiene %s de %s' % (actual.factor, actual.actualizado.strftime('%d/%m'))
                            if actual else 'no hay valor anterior')
                self.stderr.write(self.style.WARNING('  %-5s FALLO: %s (%s)' % (tienda, exc, anterior)))
                continue

            factor = resultado['factor']
            descuento = (Decimal('1') - factor) * 100
            self.stdout.write('  %-5s = %s USD  (%.1f%% de descuento, %s ofertas leidas)'
                              % (tienda, factor, descuento, resultado['muestras']))
            if not dry_run:
                TasaTienda.objects.update_or_create(
                    tienda=tienda,
                    defaults={
                        'factor': factor,
                        'muestras': resultado['muestras'],
                        'manual': False,
                        'nota': 'Mediana de las 3 mejores: %s' % '; '.join(
                            '%s (%s)' % (t[:40], f) for t, f in resultado['usadas']),
                    },
                )

    def _dolar(self, actual, trm, forzar):
        """Lo que cuesta de verdad un dolar: el USDT mas barato de Binance P2P.

        El saldo de las tiendas se compra en buysellvouchers y se paga con
        USDT, asi que el dolar del negocio es lo que cuesta ese USDT, no la
        TRM. Devuelve None cuando no hay que escribir nada: la fila esta en
        manual, o Binance fallo y se conserva el valor anterior.
        """
        if actual and actual.manual and not forzar:
            self.stdout.write('  USD = %s COP (manual, sin tocar).' % actual.cop_por_unidad)
            return None

        usdt = self._usdt_binance()
        if usdt is not None and abs(usdt / trm - 1) > DESVIO_MAXIMO_USDT:
            self.stderr.write(self.style.WARNING(
                '  USDT de Binance a %s COP se aleja mas de %s%% de la TRM (%s); se descarta.'
                % (usdt, int(DESVIO_MAXIMO_USDT * 100), trm)))
            usdt = None

        if usdt is not None:
            self.stdout.write('  USDT mas barato en Binance P2P: %s COP (%.1f%% bajo la TRM)'
                              % (usdt, (1 - usdt / trm) * 100))
            return usdt
        if actual:
            self.stderr.write(self.style.WARNING('  USD: se mantiene %s de %s.'
                              % (actual.cop_por_unidad, actual.actualizado.strftime('%d/%m'))))
            return None
        # Sin Binance y sin valor anterior, la TRM es mejor que dejar al radar sin dolar.
        self.stderr.write(self.style.WARNING('  USD: no hay valor anterior, se siembra con la TRM.'))
        return trm

    def _usdt_binance(self):
        """El anuncio mas barato de USDT por pesos en Binance P2P."""
        cuerpo = {
            'fiat': 'COP', 'asset': 'USDT', 'tradeType': 'BUY',
            'page': 1, 'rows': 10, 'payTypes': [], 'publisherType': None,
        }
        try:
            r = requests.post(API_BINANCE_P2P, json=cuerpo, timeout=30)
            r.raise_for_status()
            precios = [Decimal(str(a['adv']['price'])) for a in r.json().get('data') or []]
        except (requests.RequestException, ValueError, KeyError, TypeError, InvalidOperation) as exc:
            self.stderr.write(self.style.WARNING('  No se pudo leer Binance P2P: %s' % exc))
            return None
        if not precios:
            self.stderr.write(self.style.WARNING('  Binance P2P no devolvio anuncios de USDT/COP.'))
            return None
        return min(precios)

    def _trm(self):
        """TRM oficial: el dolar de mercado, el que pagaria el cliente."""
        try:
            r = requests.get(API_TRM, timeout=20)
            r.raise_for_status()
            filas = r.json()
            if filas:
                return Decimal(str(filas[0]['valor']))
        except (requests.RequestException, ValueError, KeyError, IndexError, InvalidOperation):
            self.stderr.write(self.style.WARNING('  No se pudo leer la TRM oficial; se usa la tasa de mercado.'))
        return None
