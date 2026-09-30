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
    MapeoConsola,
    ParametrosRadar,
    PrecioRegional,
    TasaCambio,
    TasaTienda,
    buscador_de_catalogo,
    retirar_ofertas_desaparecidas,
)
from radar.tiendas import xbox

REGIONES_COMPRA = ['TR', 'IN', 'SA', 'US']


# La tienda manda los titulos en ingles y el catalogo propio esta en espanol,
# asi que "Assassin's Creed Valhalla Complete Edition" no cruzaba con
# "ASSASSIN'S CREED VALHALLA EDICION COMPLETA" y el juego aparecia como si no
# lo vendieramos.
#
# Las palabras de edicion NO se borran, se traducen a una sola forma. Borrarlas
# seria peor: el catalogo tiene Valhalla a secas, Valhalla Gold y Valhalla
# Edicion Completa, y sin esas palabras los tres colapsan en la misma clave --
# un cruce equivocado es peor que ninguno, porque lleva a tocarle el precio al
# producto que no era.
EDICIONES = {
    'completa': 'complete', 'completo': 'complete', 'complete': 'complete',
    'oro': 'gold', 'gold': 'gold',
    'definitiva': 'definitive', 'definitive': 'definitive',
    'deluxe': 'deluxe',
    'ultimate': 'ultimate',
    'premium': 'premium',
    'aniversario': 'anniversary', 'anniversary': 'anniversary',
    'remasterizado': 'remastered', 'remasterizada': 'remastered',
    'remastered': 'remastered',
    'goty': 'goty',
}

# Palabras que no distinguen una edicion de otra y solo estorban al cruzar.
RELLENO = {'edicion', 'edition', 'standard', 'estandar', 'ingles', 'english',
           'espanol', 'spanish'}


def normalizar(titulo):
    """Normaliza un titulo para poder cruzarlo con el catalogo propio."""
    # Los simbolos se quitan ANTES de unidecode, y ese orden es el arreglo.
    # unidecode traduce los simbolos a letras -- (tm), (r), (c) -- asi que
    # "NieR:Automata(tm) BECOME as GODS Edition" quedaba como
    # "nier automata tm become as gods" y nunca cruzaba con el catalogo, que
    # escribe el titulo sin el simbolo. Xbox los pone en casi todos los
    # titulos, asi que esto solo se notaba como "el cruce no funciona".
    for simbolo in ('™', '®', '©'):
        titulo = (titulo or '').replace(simbolo, ' ')
    try:
        from unidecode import unidecode
        titulo = unidecode(titulo)
    except ImportError:
        pass
    titulo = re.sub(r'[^a-z0-9]+', ' ', titulo.lower())
    palabras = []
    for palabra in titulo.split():
        if palabra in RELLENO:
            continue
        palabras.append(EDICIONES.get(palabra, palabra))
    return ' '.join(palabras)


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

        self.fallidas = []
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
            ejecucion.ok = juegos > 0 and not self.fallidas
            ejecucion.juegos_vistos = juegos
            ejecucion.precios_guardados = precios_guardados
            if self.fallidas:
                ejecucion.error = 'Regiones que fallaron: %s' % ' | '.join(self.fallidas)
            ejecucion.save()

        if juegos == 0:
            # Cero ofertas no es un resultado plausible: la tienda siempre tiene.
            # Es la senal de que un endpoint cambio y hay que repararlo.
            self.stderr.write(self.style.ERROR(
                'El radar no encontro ninguna oferta. Eso no es normal: revisa si el '
                'endpoint de Xbox cambio (ver docs/radar-ofertas.md).'
            ))
            raise SystemExit(1)

        if self.fallidas:
            self.stderr.write(self.style.WARNING(
                'Corrida PARCIAL: fallaron %s de las regiones pedidas (%s). Los datos de las '
                'demas si se guardaron.' % (len(self.fallidas), ' | '.join(self.fallidas))))

        self.stdout.write(self.style.SUCCESS(
            'Radar Xbox listo: %s juegos, %s precios regionales.' % (juegos, precios_guardados)
        ))

    def _correr(self, regiones, max_paginas, minimo, dry_run, parametros):
        sesion = xbox._sesion()
        log = lambda m: self.stdout.write(m)

        # 1. Ofertas de cada region de compra.
        #
        # Una region que falla no debe tumbar la corrida entera: las otras tres
        # traen datos perfectamente utiles, y perderlos por un corte de red de
        # tres segundos en la cuarta seria absurdo. Lo que si queda es el rastro
        # de cual fallo, para que no pase inadvertido.
        por_region = {}
        self.fallidas = []
        for region in regiones:
            self.stdout.write('Revisando ofertas en %s...' % region)
            try:
                encontradas = xbox.ofertas(
                    region, max_paginas=max_paginas, descuento_minimo=minimo, sesion=sesion, log=log,
                )
            except xbox.ErrorTienda as exc:
                self.fallidas.append('%s: %s' % (region, exc))
                self.stderr.write(self.style.WARNING('  %s FALLO: %s' % (region, exc)))
                continue
            por_region[region] = encontradas
            self.stdout.write('  %s: %s ofertas' % (region, len(encontradas)))

        if not por_region:
            raise xbox.ErrorTienda(
                'Fallaron todas las regiones. No es un corte de red: revisa si el endpoint '
                'de Xbox cambio (ver docs/radar-ofertas.md). Detalle: %s' % ' | '.join(self.fallidas))

        regiones = [r for r in regiones if r in por_region]

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
        # El saldo de Xbox se compra como gift card con descuento, asi que un
        # dolar gastado alli cuesta menos que un dolar de mercado. Usar la TRM
        # a secas subestimaria el margen y descartaria oportunidades reales.
        tasa_tienda = TasaTienda.objects.filter(tienda='XBOX').first()
        if tasa_tienda and 'USD' in tasas:
            tasas['USD'] = (tasas['USD'] * tasa_tienda.factor)
            self.stdout.write('  Dolar de saldo Xbox: factor %s -> %s COP por dolar'
                              % (tasa_tienda.factor, tasas['USD'].quantize(Decimal('0.01'))))
        faltantes = sorted({o['moneda'] for lista in por_region.values() for o in lista if o['moneda'] not in tasas})
        if faltantes:
            self.stderr.write(self.style.WARNING(
                'Sin tasa de cambio para: %s. Esos costos quedan sin convertir. '
                'Corre primero: manage.py radar_tasas' % ', '.join(faltantes)
            ))

        # Si la tienda estrena una plataforma, que aparezca sola en el admin
        # para poder asignarle consola. Mejor eso que descubrirlo por un juego
        # que no se publica.
        vistas = {parte.strip() for f in fichas.values()
                  for parte in (f.get('plataformas') or '').split(',') if parte.strip()}
        conocidas = set(MapeoConsola.objects.values_list('plataforma', flat=True))
        for nueva in sorted(vistas - conocidas):
            MapeoConsola.objects.create(plataforma=nueva)
            self.stdout.write('  plataforma nueva detectada: %s (asignale consola en el admin)' % nueva)

        catalogo = buscador_de_catalogo(normalizar, 'XBOX', parametros)
        guardados = 0

        with transaction.atomic():
            for big_id, ficha in fichas.items():
                ref = referencia.get(big_id) or {}
                # El titulo de Colombia manda: el del listado viene en el
                # idioma del pais donde se compra, y es el que ve el cliente.
                titulo = ref.get('titulo') or ficha['titulo']
                juego, _ = JuegoDetectado.objects.update_or_create(
                    tienda='XBOX', id_externo=big_id,
                    defaults={
                        'titulo': titulo,
                        'descripcion': ref.get('descripcion') or ficha['descripcion'],
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
                        'producto_existente_id': catalogo(titulo),
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

        # Lo que la tienda dejo de listar tiene que salir del radar, o su
        # precio viejo sigue apareciendo como oportunidad para siempre.
        vistos = {region: {o['id_externo'] for o in por_region[region]} for region in regiones}
        precios_fuera, juegos_fuera, saltadas = retirar_ofertas_desaparecidas('XBOX', vistos)
        if precios_fuera or juegos_fuera:
            self.stdout.write('Ya no estan en oferta: %s precios y %s juegos salieron del radar.'
                              % (precios_fuera, juegos_fuera))
        for region, vistos_region, guardados in saltadas:
            self.stderr.write(self.style.WARNING(
                '  %s: la tienda devolvio %s ofertas y hay %s guardadas. Parece una lectura '
                'a medias, asi que no se borro nada de esa region.'
                % (region, vistos_region, guardados)))

        return len(fichas), guardados

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
