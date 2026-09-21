# -*- coding: utf-8 -*-
"""Actualiza las tasas de cambio que usa el radar para convertir a pesos."""
from decimal import Decimal, InvalidOperation

import requests
from django.core.management.base import BaseCommand

from radar.models import TasaCambio

# Base USD, gratis y sin llave. Cubre COP, TRY, INR y SAR.
API_TASAS = 'https://open.er-api.com/v6/latest/USD'
# TRM oficial de Colombia, solo para sembrar el valor inicial del dolar.
API_TRM = 'https://www.datos.gov.co/resource/32sa-8pi3.json?$limit=1&$order=vigenciadesde%20DESC'

# Monedas de las regiones de compra del negocio.
MONEDAS = ['USD', 'TRY', 'INR', 'SAR']

NOTAS = {
    'USD': 'Manual: el dolar se consigue por debajo de la TRM. Editar con el costo real.',
    'SAR': 'El rial esta anclado al dolar a 3,75 desde 1986.',
}


class Command(BaseCommand):
    help = (
        'Actualiza las tasas de cambio del radar (cuantos pesos vale una unidad de cada '
        'moneda de compra). Las tasas marcadas como manuales NO se tocan: el dolar es '
        'manual a proposito, porque se consigue por debajo de la TRM y ese descuento es '
        'margen que ninguna API conoce.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--forzar-usd', action='store_true',
            help='Sobrescribe tambien el dolar con la TRM oficial, pisando el valor manual.',
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
        escritas = 0

        for moneda in MONEDAS:
            actual = existentes.get(moneda)

            if moneda == 'USD':
                valor = self._trm() or cop_por_usd
                if actual and actual.manual and not forzar_usd:
                    self.stdout.write(
                        '  USD = %s COP (manual, sin tocar). Referencia de mercado: %s'
                        % (actual.cop_por_unidad, valor)
                    )
                    continue
                manual = True
            else:
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
                manual = False

            valor = valor.quantize(Decimal('0.000001'))
            self.stdout.write('  %s = %s COP%s' % (moneda, valor, ' (manual)' if manual else ''))

            if not dry_run:
                TasaCambio.objects.update_or_create(
                    moneda=moneda,
                    defaults={
                        'cop_por_unidad': valor,
                        'manual': manual,
                        'nota': NOTAS.get(moneda, ''),
                    },
                )
                escritas += 1

        if dry_run:
            self.stdout.write(self.style.WARNING('Modo --dry-run: no se escribio nada.'))
        else:
            self.stdout.write(self.style.SUCCESS('Tasas actualizadas: %s' % escritas))

    def _trm(self):
        """TRM oficial, solo como valor inicial del dolar."""
        try:
            r = requests.get(API_TRM, timeout=20)
            r.raise_for_status()
            filas = r.json()
            if filas:
                return Decimal(str(filas[0]['valor']))
        except (requests.RequestException, ValueError, KeyError, IndexError, InvalidOperation):
            self.stderr.write(self.style.WARNING('  No se pudo leer la TRM oficial; se usa la tasa de mercado.'))
        return None
