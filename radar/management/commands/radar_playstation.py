# -*- coding: utf-8 -*-
"""Radar de ofertas de la PlayStation Store.

Mismo trabajo que radar_xbox, con una diferencia que manda en el diseno: Sony
no tiene identificador global. Colombia y USA comparten zona y cruzan por SKU
(90% medido); Turquia es otra zona y cruza al 70% sumando SKU y titulo
normalizado. Lo que no cruza es, casi siempre, un juego que Colombia no tiene
en oferta: sin precio de referencia no hay margen que calcular.

    docker exec hc-django python manage.py radar_playstation
"""
import traceback
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from radar.management.commands.radar_xbox import normalizar
from radar.models import (
    EjecucionRadar,
    JuegoDetectado,
    ParametrosRadar,
    PrecioRegional,
    TasaCambio,
    TasaTienda,
)
from radar.tiendas import playstation

REGIONES_COMPRA = ['US', 'TR']
REGION_REFERENCIA = 'CO'


class Command(BaseCommand):
    help = (
        'Revisa las ofertas de la PlayStation Store en las regiones de compra (USA y '
        'Turquia), las cruza con el precio de Colombia y guarda el costo en pesos. '
        'No publica nada.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--regiones', default=','.join(REGIONES_COMPRA))
        parser.add_argument(
            '--max-detalles', type=int, default=400,
            help='Cuantas fechas de vencimiento consultar (una peticion cada una). '
                 'Se piden solo para lo mas rentable (default 400).',
        )
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        regiones = [r.strip().upper() for r in options['regiones'].split(',') if r.strip()]
        parametros = ParametrosRadar.actuales()

        ejecucion = None
        if not dry_run:
            ejecucion = EjecucionRadar.objects.create(tienda='PS', regiones=','.join(regiones))

        try:
            juegos, precios = self._correr(regiones, options['max_detalles'], dry_run, parametros)
        except Exception as exc:
            if ejecucion:
                ejecucion.fin = timezone.now()
                ejecucion.ok = False
                ejecucion.error = '%s\n%s' % (exc, traceback.format_exc())
                ejecucion.save()
            self.stderr.write(self.style.ERROR('El radar de PlayStation fallo: %s' % exc))
            raise SystemExit(1)

        if ejecucion:
            ejecucion.fin = timezone.now()
            ejecucion.ok = juegos > 0
            ejecucion.juegos_vistos = juegos
            ejecucion.precios_guardados = precios
            ejecucion.save()

        if juegos == 0:
            self.stderr.write(self.style.ERROR(
                'No se cruzo ningun juego. Revisa si Sony roto el sha256Hash '
                '(ver docs/radar-ofertas.md).'))
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS(
            'Radar PlayStation listo: %s juegos, %s precios regionales.' % (juegos, precios)))

    def _correr(self, regiones, max_detalles, dry_run, parametros):
        sesion = playstation._sesion()
        log = lambda m: self.stdout.write(m)

        self.stdout.write('Leyendo ofertas de Colombia (referencia)...')
        referencia = playstation.ofertas(REGION_REFERENCIA, sesion=sesion, log=log)
        por_sku = {o['id_externo']: o for o in referencia}
        por_titulo = {}
        for o in referencia:
            por_titulo.setdefault(o['titulo_normalizado'], o)

        compras = {}
        for region in regiones:
            self.stdout.write('Leyendo ofertas de %s...' % region)
            compras[region] = playstation.ofertas(region, sesion=sesion, log=log)

        # Cruce: primero por SKU (exacto), luego por titulo normalizado.
        cruzados = {}
        sin_cruce = 0
        for region, lista in compras.items():
            for oferta in lista:
                base = por_sku.get(oferta['id_externo']) or por_titulo.get(oferta['titulo_normalizado'])
                if base is None:
                    sin_cruce += 1
                    continue
                entrada = cruzados.setdefault(base['id_externo'], {'base': base, 'regiones': {}})
                entrada['regiones'][region] = oferta

        self.stdout.write('Cruzados: %s juegos. Sin precio de Colombia: %s (se omiten).'
                          % (len(cruzados), sin_cruce))
        if not cruzados:
            return 0, 0

        tasas = TasaCambio.mapa()
        tasa_ps = TasaTienda.objects.filter(tienda='PS').first()
        if tasa_ps and 'USD' in tasas:
            # El saldo de PSN se compra como gift card con descuento, igual que
            # el de Xbox pero con otro factor.
            tasas['USD'] = tasas['USD'] * tasa_ps.factor
            self.stdout.write('  Dolar de saldo PSN: factor %s -> %s COP'
                              % (tasa_ps.factor, tasas['USD'].quantize(Decimal('0.01'))))

        # La tienda colombiana de PS cotiza en dolares, asi que el precio de
        # referencia hay que pasarlo a pesos. Aqui se usa el dolar de mercado,
        # no el de saldo: es lo que pagaria el cliente comprando el solo.
        usd_mercado = TasaCambio.objects.filter(moneda='USD').first()
        usd_mercado = usd_mercado.cop_por_unidad if usd_mercado else None
        if not usd_mercado:
            raise playstation.ErrorTienda(
                'Falta la tasa del dolar. Corre antes: manage.py radar_tasas')

        # Las fechas de vencimiento cuestan una peticion por juego, asi que solo
        # se piden para los que se ven rentables: el resto no se va a publicar.
        candidatos = self._ordenar_por_margen(cruzados, tasas, usd_mercado, parametros)
        self.stdout.write('Consultando vencimiento de los %s mas rentables...'
                          % min(max_detalles, len(candidatos)))

        if dry_run:
            self._resumen(candidatos[:30], usd_mercado)
            self.stdout.write(self.style.WARNING('Modo --dry-run: no se escribio nada.'))
            return len(cruzados), 0

        catalogo = self._catalogo_propio()
        guardados = 0

        for indice, (margen, clave, region, costo) in enumerate(candidatos):
            entrada = cruzados[clave]
            base = entrada['base']
            fin = None
            if indice < max_detalles:
                try:
                    detalle = playstation.detalle(
                        entrada['regiones'][region]['id_externo'], region, sesion=sesion)
                    fin = detalle['fecha_fin']
                except playstation.ErrorTienda as exc:
                    self.stderr.write(self.style.WARNING('  sin vencimiento para %s: %s'
                                                         % (base['titulo'][:40], exc)))

            with transaction.atomic():
                juego, _ = JuegoDetectado.objects.update_or_create(
                    tienda='PS', id_externo=clave,
                    defaults={
                        'titulo': base['titulo'],
                        'imagen': base['imagen'],
                        'plataformas': base['plataformas'],
                        'precio_co': (base['precio_lista'] or 0) * usd_mercado,
                        'precio_co_oferta': (base['precio_oferta'] or 0) * usd_mercado,
                        'comprable_co': True,
                        'producto_existente_id': catalogo.get(normalizar(base['titulo'])),
                    },
                )
                for reg, oferta in entrada['regiones'].items():
                    PrecioRegional.objects.update_or_create(
                        juego=juego, region=reg,
                        defaults={
                            'moneda': oferta['moneda'],
                            'precio_lista': oferta['precio_lista'],
                            'precio_oferta': oferta['precio_oferta'],
                            'descuento_pct': oferta['descuento_pct'],
                            'comprable': True,
                            'fecha_fin': fin if reg == region else None,
                            'costo_cop': _a_pesos(oferta['precio_oferta'], oferta['moneda'], tasas),
                        },
                    )
                    guardados += 1

        return len(cruzados), guardados

    def _ordenar_por_margen(self, cruzados, tasas, usd_mercado, parametros):
        filas = []
        for clave, entrada in cruzados.items():
            base = entrada['base']
            precio_co = (base['precio_oferta'] or base['precio_lista'] or 0) * usd_mercado
            if not precio_co:
                continue
            venta = int(precio_co * parametros.factor_precio_venta)
            for region, oferta in entrada['regiones'].items():
                costo = _a_pesos(oferta['precio_oferta'], oferta['moneda'], tasas)
                if costo is None:
                    continue
                filas.append((venta - costo, clave, region, costo))
        filas.sort(reverse=True)
        return filas

    def _resumen(self, filas, usd_mercado):
        self.stdout.write('')
        self.stdout.write('%-46s %-4s %12s %12s' % ('JUEGO', 'REG', 'COSTO', 'MARGEN'))
        self.stdout.write('-' * 80)
        for margen, clave, region, costo in filas:
            self.stdout.write('%-46s %-4s %12s %12s' % (clave[:46], region, costo, margen))

    def _catalogo_propio(self):
        try:
            from products.models import Products
            return {normalizar(t): pid
                    for pid, t in Products.objects.values_list('id_product', 'title') if t}
        except Exception as exc:
            self.stderr.write(self.style.WARNING('No se pudo leer el catalogo propio: %s' % exc))
            return {}


def _a_pesos(valor, moneda, tasas):
    if valor is None or moneda not in tasas:
        return None
    try:
        return int(Decimal(str(valor)) * tasas[moneda])
    except Exception:
        return None
