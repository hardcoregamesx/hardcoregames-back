# -*- coding: utf-8 -*-
"""Radar de ofertas de la tienda Xbox.

Recorre las regiones de compra, guarda cada oferta con su ficha y su fecha de
vencimiento, y le pone al lado el precio de referencia de Colombia para poder
calcular el margen.

Pensado para correr una vez al dia:
    docker exec hc-django python manage.py radar_xbox >> /opt/hardcoregames/radar.log 2>&1
"""
import re
import traceback
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from radar.models import (
    REGION_REFERENCIA,
    EjecucionRadar,
    JuegoDetectado,
    ParametrosRadar,
    PrecioRegional,
    TasaCambio,
)
from radar.tiendas import xbox

REGIONES_COMPRA = ['TR', 'IN', 'SA', 'US']


def normalizar(titulo):
    """Normaliza un titulo para poder cruzarlo con el catalogo propio."""
    try:
        from unidecode import unidecode
        titulo = unidecode(titulo)
    except ImportError:
        pass
    titulo = titulo.lower()
    # Fuera sufijos de edicion, que son la causa mas comun de falsos negativos.
    titulo = re.sub(r'\b(edicion|edition|deluxe|ultimate|standard|estandar|goty|remastered)\b', ' ', titulo)
    titulo = re.sub(r'[^a-z0-9]+', ' ', titulo)
    return ' '.join(titulo.split())


class Command(BaseCommand):
    help = (
        'Revisa las ofertas vigentes de la tienda Xbox en las regiones de compra '
        '(Turquia, India, Arabia Saudita y USA), trae el precio de referencia de '
        'Colombia y guarda todo con el costo ya convertido a pesos. No publica nada: '
        'solo recoge datos para decidir.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--regiones', default=','.join(REGIONES_COMPRA),
            help='Regiones de compra separadas por coma (default: %s).' % ','.join(REGIONES_COMPRA),
        )
        parser.add_argument(
            '--max-paginas', type=int, default=60,
            help='Tope de paginas por region, por seguridad (default 60; el catalogo real usa ~40).',
        )
        parser.add_argument(
            '--min-descuento', type=float, default=None,
            help='Descuento minimo a considerar. Por defecto usa el de Parametros del radar.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Consulta las tiendas y muestra el resumen, sin escribir en la base.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        regiones = [r.strip().upper() for r in options['regiones'].split(',') if r.strip()]
        parametros = ParametrosRadar.actuales()
        minimo = options['min_descuento']
        if minimo is None:
            minimo = float(parametros.descuento_minimo_pct)

        desconocidas = [r for r in regiones if r not in xbox.REGIONES]
        if desconocidas:
            self.stderr.write(self.style.ERROR('Regiones desconocidas: %s' % ', '.join(desconocidas)))
            raise SystemExit(2)

        ejecucion = None
        if not dry_run:
            ejecucion = EjecucionRadar.objects.create(tienda='XBOX', regiones=','.join(regiones))

        try:
            resultado = self._correr(regiones, options['max_paginas'], minimo, dry_run, parametros)
        except Exception as exc:
            if ejecucion:
                ejecucion.fin = timezone.now()
                ejecucion.ok = False
                ejecucion.error = '%s\n%s' % (exc, traceback.format_exc())
                ejecucion.save()
            self.stderr.write(self.style.ERROR('El radar fallo: %s' % exc))
            # Salir con codigo distinto de cero para que el cron lo note.
            raise SystemExit(1)

        juegos, precios_guardados = resultado

        if ejecucion:
            ejecucion.fin = timezone.now()
            ejecucion.ok = juegos > 0
            ejecucion.juegos_vistos = juegos
            ejecucion.precios_guardados = precios_guardados
            ejecucion.save()

        if juegos == 0:
            # Cero ofertas no es un resultado plausible: la tienda siempre tiene.
            # Es la senal de que un endpoint cambio y hay que repararlo.
            self.stderr.write(self.style.ERROR(
                'El radar no encontro ninguna oferta. Eso no es normal: revisa si el '
                'endpoint de Xbox cambio (ver docs/radar-ofertas.md).'
            ))
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS(
            'Radar Xbox listo: %s juegos, %s precios regionales.' % (juegos, precios_guardados)
        ))

    def _correr(self, regiones, max_paginas, minimo, dry_run, parametros):
        sesion = xbox._sesion()
        log = lambda m: self.stdout.write(m)

        # 1. Ofertas de cada region de compra.
        por_region = {}
        for region in regiones:
            self.stdout.write('Revisando ofertas en %s...' % region)
            encontradas = xbox.ofertas(
                region, max_paginas=max_paginas, descuento_minimo=minimo, sesion=sesion, log=log,
            )
            por_region[region] = encontradas
            self.stdout.write('  %s: %s ofertas' % (region, len(encontradas)))

        # 2. Un mismo juego puede estar en oferta en varias regiones.
        fichas = {}
        for region in regiones:
            for oferta in por_region[region]:
                fichas.setdefault(oferta['id_externo'], oferta)

        if not fichas:
            return 0, 0

        # 3. Precio de referencia de Colombia, aunque alla no este en oferta.
        self.stdout.write('Consultando el precio de Colombia de %s juegos...' % len(fichas))
        referencia = xbox.precios(list(fichas.keys()), REGION_REFERENCIA, sesion=sesion, log=log)
        self.stdout.write('  Colombia: %s precios encontrados' % len(referencia))

        if dry_run:
            self._resumen(fichas, por_region, referencia, parametros)
            self.stdout.write(self.style.WARNING('Modo --dry-run: no se escribio nada.'))
            return len(fichas), 0

        tasas = TasaCambio.mapa()
        faltantes = sorted({o['moneda'] for lista in por_region.values() for o in lista if o['moneda'] not in tasas})
        if faltantes:
            self.stderr.write(self.style.WARNING(
                'Sin tasa de cambio para: %s. Esos costos quedan sin convertir. '
                'Corre primero: manage.py radar_tasas' % ', '.join(faltantes)
            ))

        catalogo = self._catalogo_propio()
        guardados = 0

        with transaction.atomic():
            for big_id, ficha in fichas.items():
                ref = referencia.get(big_id) or {}
                juego, _ = JuegoDetectado.objects.update_or_create(
                    tienda='XBOX', id_externo=big_id,
                    defaults={
                        'titulo': ficha['titulo'],
                        'descripcion': ficha['descripcion'],
                        'imagen': ficha['imagen'],
                        'generos': ficha['generos'],
                        'clasificacion': ficha['clasificacion'],
                        'plataformas': ficha['plataformas'],
                        'desarrollador': ficha['desarrollador'],
                        'rating': ficha['rating'],
                        'rating_conteo': ficha['rating_conteo'],
                        'precio_co': _dec(ref.get('precio_lista')),
                        'precio_co_oferta': _dec(ref.get('precio_oferta')),
                        'comprable_co': bool(ref),
                        'producto_existente_id': catalogo.get(normalizar(ficha['titulo'])),
                    },
                )

                for region in regiones:
                    oferta = next((o for o in por_region[region] if o['id_externo'] == big_id), None)
                    if oferta is None:
                        continue
                    PrecioRegional.objects.update_or_create(
                        juego=juego, region=region,
                        defaults={
                            'moneda': oferta['moneda'],
                            'precio_lista': _dec(oferta['precio_lista']),
                            'precio_oferta': _dec(oferta['precio_oferta']),
                            'descuento_pct': _dec(oferta['descuento_pct']) or Decimal('0'),
                            'comprable': oferta['comprable'],
                            'fecha_fin': oferta['fecha_fin'],
                            'costo_cop': _a_pesos(oferta['precio_oferta'], oferta['moneda'], tasas),
                        },
                    )
                    guardados += 1

        return len(fichas), guardados

    def _catalogo_propio(self):
        """Titulo normalizado -> id del producto que ya vendes."""
        try:
            from products.models import Products
            return {
                normalizar(t): pid
                for pid, t in Products.objects.values_list('id_product', 'title')
                if t
            }
        except Exception as exc:
            self.stderr.write(self.style.WARNING('No se pudo leer el catalogo propio: %s' % exc))
            return {}

    def _resumen(self, fichas, por_region, referencia, parametros):
        """Vista rapida de los mejores candidatos, para --dry-run."""
        tasas = TasaCambio.mapa()
        filas = []
        for big_id, ficha in fichas.items():
            ref = referencia.get(big_id)
            if not ref:
                continue
            base = ref.get('precio_oferta') or ref.get('precio_lista')
            if not base:
                continue
            venta = int(Decimal(str(base)) * parametros.factor_precio_venta)
            for region, lista in por_region.items():
                oferta = next((o for o in lista if o['id_externo'] == big_id), None)
                if not oferta or not oferta['comprable']:
                    continue
                costo = _a_pesos(oferta['precio_oferta'], oferta['moneda'], tasas)
                if costo is None:
                    continue
                filas.append((venta - costo, ficha['titulo'], region, costo, venta, ficha['rating_conteo']))

        filas.sort(reverse=True)
        viables = [f for f in filas if f[0] >= parametros.margen_minimo_cop]
        self.stdout.write('')
        self.stdout.write('Candidatos que pasan el filtro: %s de %s combinaciones' % (len(viables), len(filas)))
        for margen, titulo, region, costo, venta, resenas in viables[:25]:
            self.stdout.write('  %-44s %s  costo %8s  venta %8s  margen %8s  (%s resenas)' % (
                titulo[:44], region, costo, venta, margen, resenas))


def _dec(valor):
    if valor is None:
        return None
    try:
        return Decimal(str(valor))
    except Exception:
        return None


def _a_pesos(valor, moneda, tasas):
    if valor is None or moneda not in tasas:
        return None
    try:
        return int(Decimal(str(valor)) * tasas[moneda])
    except Exception:
        return None
