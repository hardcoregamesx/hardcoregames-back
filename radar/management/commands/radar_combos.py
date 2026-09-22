# -*- coding: utf-8 -*-
"""Propone combos: varios juegos en una sola cuenta.

No publica nada. Deja borradores en el admin, sin precio, para que el dueno
los revise: quite lo que sobre, agregue lo que falte y les ponga precio. Esa
separacion es deliberada -- ninguna regla va a adivinar que golfito pega con
worms, y un combo mal armado se ve peor que no tener combos.

Tres criterios, que responden a tres formas distintas de que a alguien le
interese un paquete:

  franquicia  la saga completa que este en oferta (el combo Final Fantasy)
  genero      juegos que comparten categoria en la tienda (los cooperativos)
  baratos     titulos conocidos que cuestan poco -- muchos juegos por poca plata

Todos los juegos de un combo tienen que estar en oferta en LA MISMA region:
van a vivir en una sola cuenta.

    docker exec hc-django python manage.py radar_combos
    docker exec hc-django python manage.py radar_combos --criterio franquicia
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from radar.models import (
    COMBO_MAX_JUEGOS,
    COMBO_MIN_JUEGOS,
    Combo,
    ComboJuego,
    Franquicia,
    JuegoDetectado,
)

CRITERIOS = ['franquicia', 'genero', 'baratos']

# Un combo de "conocidos y baratos" se define por lo que cuesta, no por cuantos
# juegos trae: se van metiendo los mas populares hasta llenar el presupuesto.
COSTO_MAXIMO_POR_JUEGO = 10000
PRESUPUESTO_BARATOS = 60000


class Command(BaseCommand):
    help = (
        'Propone combos de juegos en oferta en una misma region y los deja como '
        'borradores en el admin. No publica nada ni les pone precio.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--criterio', choices=CRITERIOS + ['todos'], default='todos')
        parser.add_argument('--tienda', choices=['XBOX', 'PS', 'todas'], default='todas')
        parser.add_argument(
            '--costo-maximo', type=int, default=COSTO_MAXIMO_POR_JUEGO,
            help='Tope de costo por juego para el criterio "baratos" (default %s).'
                 % COSTO_MAXIMO_POR_JUEGO,
        )
        parser.add_argument(
            '--presupuesto', type=int, default=PRESUPUESTO_BARATOS,
            help='Costo total al que apunta un combo de baratos (default %s).'
                 % PRESUPUESTO_BARATOS,
        )
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        criterios = CRITERIOS if options['criterio'] == 'todos' else [options['criterio']]
        tiendas = ['XBOX', 'PS'] if options['tienda'] == 'todas' else [options['tienda']]

        # Un juego solo sirve para un combo si se puede comprar HOY en alguna
        # region: el combo hereda la fecha de fin mas temprana de sus juegos, y
        # partir de uno ya vencido es armar algo que nace muerto.
        ahora = timezone.now()
        disponibles = defaultdict(list)   # (tienda, region) -> [juego, ...]
        for juego in (JuegoDetectado.objects
                      .exclude(estado__in=['descartado', 'vencido'])
                      .prefetch_related('precios')):
            if juego.tienda not in tiendas:
                continue
            for precio in juego.precios.all():
                if not precio.comprable or not precio.costo_cop:
                    continue
                if precio.fecha_fin and precio.fecha_fin <= ahora:
                    continue
                disponibles[(juego.tienda, precio.region)].append(juego)

        if not disponibles:
            self.stdout.write(self.style.WARNING(
                'No hay juegos en oferta vigente. Corre antes el radar de la tienda.'))
            return

        propuestas = []
        for (tienda, region), juegos in sorted(disponibles.items()):
            for criterio in criterios:
                propuestas += getattr(self, '_por_%s' % criterio)(
                    tienda, region, juegos, options)

        propuestas = self._sin_repetidos(propuestas)
        if not propuestas:
            self.stdout.write('Ningun grupo llego a %s juegos en una misma region.'
                              % COMBO_MIN_JUEGOS)
            return

        self.stdout.write('')
        for propuesta in propuestas:
            self.stdout.write('  [%s] %s (%s, %s juegos, te cuesta %s)' % (
                propuesta['origen'], propuesta['nombre'], propuesta['region'],
                len(propuesta['juegos']), _pesos(propuesta['costo'])))

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                '\nModo --dry-run: no se guardo nada. Serian %s combos.' % len(propuestas)))
            return

        creados = self._guardar(propuestas)
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            '%s combos nuevos, como borradores sin precio.' % creados))
        self.stdout.write(
            'Revisalos en el admin -> Radar de ofertas -> Combos: quita lo que sobre, '
            'ponles precio y publica.')

    # --- criterios ----------------------------------------------------------

    def _por_franquicia(self, tienda, region, juegos, options):
        """La saga completa que este en oferta a la vez."""
        terminos = list(Franquicia.objects.filter(activa=True).values_list('termino', flat=True))
        propuestas = []
        for termino in terminos:
            miembros = [j for j in juegos if termino in (j.titulo or '').lower()]
            miembros = self._recortar(miembros)
            if len(miembros) < COMBO_MIN_JUEGOS:
                continue
            propuestas.append(self._propuesta(
                'franquicia', 'Combo %s' % termino.title(), tienda, region, miembros))
        return propuestas

    def _por_genero(self, tienda, region, juegos, options):
        """Juegos que comparten categoria en la tienda.

        Las categorias vienen de la propia tienda ("Co-op", "Accion y
        aventura"), asi que el grupo sale del dato y no de una lista mia que
        habria que mantener.
        """
        por_genero = defaultdict(list)
        for juego in juegos:
            for genero in (juego.generos or '').split(','):
                genero = genero.strip()
                if genero:
                    por_genero[genero].append(juego)

        propuestas = []
        for genero, miembros in por_genero.items():
            # Los mas conocidos primero: un combo de genero con nueve titulos
            # que nadie reconoce no lo compra nadie.
            miembros = self._recortar(sorted(
                miembros, key=lambda j: j.rating_conteo or 0, reverse=True))
            if len(miembros) < COMBO_MIN_JUEGOS:
                continue
            propuestas.append(self._propuesta(
                'genero', 'Combo %s' % genero.lower(), tienda, region, miembros))
        return propuestas

    def _por_baratos(self, tienda, region, juegos, options):
        """Titulos conocidos que cuestan poco, hasta llenar el presupuesto.

        "Conocido" no es el numero de resenas sino estar en la lista de
        franquicias: es la definicion que ya existe en el admin y la que usa el
        dueno para decidir. Un indie con muchas resenas no vende igual que un
        Batman.
        """
        terminos = list(Franquicia.objects.filter(activa=True).values_list('termino', flat=True))
        tope = options['costo_maximo']
        candidatos = []
        for juego in juegos:
            costo = self._costo(juego, region)
            if costo is None or costo > tope:
                continue
            if not any(t in (juego.titulo or '').lower() for t in terminos):
                continue
            candidatos.append((costo, juego))

        # Del mas conocido al menos, no del mas barato: el presupuesto ya
        # garantiza que sea barato, lo que hay que maximizar es el gancho.
        candidatos.sort(key=lambda par: par[1].rating_conteo or 0, reverse=True)

        elegidos, acumulado = [], 0
        for costo, juego in candidatos:
            if len(elegidos) >= COMBO_MAX_JUEGOS:
                break
            if acumulado + costo > options['presupuesto'] and elegidos:
                continue
            elegidos.append(juego)
            acumulado += costo
        if len(elegidos) < COMBO_MIN_JUEGOS:
            return []
        return [self._propuesta('baratos', 'Combo economico', tienda, region, elegidos)]

    # --- utilidades ---------------------------------------------------------

    def _recortar(self, miembros):
        return miembros[:COMBO_MAX_JUEGOS]

    def _costo(self, juego, region):
        precio = next((p for p in juego.precios.all() if p.region == region), None)
        if precio is None or precio.costo_cop is None:
            return None
        return int(precio.costo_cop)

    def _propuesta(self, origen, nombre, tienda, region, juegos):
        costo = sum(self._costo(j, region) or 0 for j in juegos)
        return {'origen': origen, 'nombre': nombre, 'tienda': tienda,
                'region': region, 'juegos': juegos, 'costo': costo}

    def _sin_repetidos(self, propuestas):
        """Dos criterios pueden proponer el mismo conjunto de juegos.

        Pasa seguido: la saga Crash tambien cae en "baratos conocidos". Se
        conserva la primera, que viene del criterio mas especifico.
        """
        vistas = set()
        unicas = []
        for propuesta in propuestas:
            firma = (propuesta['tienda'], propuesta['region'],
                     tuple(sorted(j.pk for j in propuesta['juegos'])))
            if firma in vistas:
                continue
            vistas.add(firma)
            unicas.append(propuesta)
        return unicas

    def _guardar(self, propuestas):
        """Guarda los borradores, saltando los que ya existen.

        El comando esta pensado para correrse seguido, asi que no puede
        duplicar: si ya hay un combo con los mismos juegos en la misma region,
        se deja el que esta -- puede tener precio puesto a mano.
        """
        existentes = set()
        for combo in Combo.objects.prefetch_related('items'):
            existentes.add((combo.tienda, combo.region,
                            tuple(sorted(i.juego_id for i in combo.items.all()))))

        creados = 0
        for propuesta in propuestas:
            firma = (propuesta['tienda'], propuesta['region'],
                     tuple(sorted(j.pk for j in propuesta['juegos'])))
            if firma in existentes:
                continue
            with transaction.atomic():
                combo = Combo.objects.create(
                    nombre=propuesta['nombre'][:120],
                    tienda=propuesta['tienda'],
                    region=propuesta['region'],
                    origen=propuesta['origen'],
                )
                for orden, juego in enumerate(propuesta['juegos']):
                    ComboJuego.objects.create(combo=combo, juego=juego, orden=orden)
                combo.descripcion = combo.descripcion_generada()
                combo.save(update_fields=['descripcion'])
            existentes.add(firma)
            creados += 1
        return creados


def _pesos(valor):
    if valor is None:
        return '-'
    return '$ {:,.0f}'.format(valor).replace(',', '.')
