# -*- coding: utf-8 -*-
"""Reporte de las oportunidades que el radar tiene guardadas hoy.

Durante la fase de recoleccion este comando es la forma de mirar los datos sin
publicar nada: responde cuantas oportunidades reales aparecen por semana, con
que margen y desde que region.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from radar.models import EjecucionRadar, JuegoDetectado, ParametrosRadar


def pesos(valor):
    if valor is None:
        return '-'
    return '{:,.0f}'.format(valor).replace(',', '.')


class Command(BaseCommand):
    help = (
        'Lista las oportunidades vigentes que el radar tiene guardadas, ordenadas por '
        'margen. Muestra costo en la mejor region, precio de venta sugerido, margen y '
        'cuando vence la promocion. No escribe nada.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--tienda', default='XBOX', help='XBOX o PS (default XBOX).')
        parser.add_argument('--top', type=int, default=40, help='Cuantas filas mostrar (default 40).')
        parser.add_argument(
            '--min-resenas', type=int, default=0,
            help='Descarta juegos con menos de N resenas en la tienda. Filtro de demanda.',
        )
        parser.add_argument(
            '--todos', action='store_true',
            help='Muestra tambien los que no alcanzan el margen minimo.',
        )
        parser.add_argument(
            '--incluir-vencidos', action='store_true',
            help='Incluye promociones cuya fecha de fin ya paso.',
        )

    def handle(self, *args, **options):
        parametros = ParametrosRadar.actuales()
        ahora = timezone.now()

        ultima = EjecucionRadar.objects.filter(tienda=options['tienda']).first()
        if ultima:
            estado = 'OK' if ultima.ok else 'FALLO'
            self.stdout.write('Ultima corrida: %s (%s), %s juegos.' % (
                ultima.inicio.strftime('%Y-%m-%d %H:%M'), estado, ultima.juegos_vistos))
            if not ultima.ok:
                self.stdout.write(self.style.ERROR(
                    'La ultima corrida fallo: los datos de abajo pueden estar viejos.'))
        else:
            self.stdout.write(self.style.WARNING('El radar todavia no ha corrido para esa tienda.'))
            return

        juegos = (JuegoDetectado.objects
                  .filter(tienda=options['tienda'])
                  .prefetch_related('precios'))

        filas = []
        for juego in juegos:
            if juego.rating_conteo < options['min_resenas']:
                continue
            venta = juego.precio_venta_sugerido(parametros)
            if venta is None:
                continue
            mejor = juego.mejor_precio()
            if mejor is None:
                continue
            if not options['incluir_vencidos'] and mejor.fecha_fin and mejor.fecha_fin < ahora:
                continue
            margen = mejor.margen(venta)
            if margen is None:
                continue
            if not options['todos'] and margen < parametros.margen_minimo_cop:
                continue
            filas.append((margen, juego, mejor, venta))

        filas.sort(key=lambda f: f[0], reverse=True)

        self.stdout.write('')
        self.stdout.write('Regla: precio Colombia x %s - costo >= %s COP' % (
            parametros.factor_precio_venta, pesos(parametros.margen_minimo_cop)))
        self.stdout.write('Oportunidades viables: %s' % len(filas))
        self.stdout.write('')
        self.stdout.write('%-42s %-4s %10s %10s %10s %10s %8s %s' % (
            'JUEGO', 'REG', 'PRECIO CO', 'COSTO', 'VENTA', 'MARGEN', 'VENCE', 'RESENAS'))
        self.stdout.write('-' * 112)

        for margen, juego, mejor, venta in filas[:options['top']]:
            marca = ' *' if juego.producto_existente_id else ''
            self.stdout.write('%-42s %-4s %10s %10s %10s %10s %8s %s%s' % (
                juego.titulo[:42],
                mejor.region,
                pesos(juego.precio_co_vigente),
                pesos(mejor.costo_cop),
                pesos(venta),
                pesos(margen),
                mejor.fecha_fin.strftime('%d/%m') if mejor.fecha_fin else '-',
                juego.rating_conteo,
                marca,
            ))

        if any(f[1].producto_existente_id for f in filas[:options['top']]):
            self.stdout.write('')
            self.stdout.write('* Ya lo tienes en catalogo: revisa si tu precio quedo alto frente a la tienda.')
