# -*- coding: utf-8 -*-
"""Busca juegos publicados que la tienda no puede vender.

Un juego publicado por el radar vive en dos sitios a la vez, y solo uno de los
dos lo sabe todo:

- la landing (/locura-xbox, /locura-playstation) saca el precio de la tabla del
  radar, asi que muestra la tarjeta aunque el producto del catalogo este vacio;
- la ficha del producto saca el precio de las variantes del catalogo, y cuando
  no hay ninguna con stock y precio, el frontend cae al modo de producto fisico:
  precio $0 y boton de "solicitar orden de compra", sin checkout.

Ese hueco era real: un juego con solo precio de cuenta y sin licencias
primaria/secundaria configuradas se publicaba sin una sola variante. La
publicacion ya no lo permite, pero lo que se publico antes sigue en la tienda,
y es lo que este comando encuentra.

    docker exec hc-django python manage.py radar_revisar
    docker exec hc-django python manage.py radar_revisar --reparar
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from radar.models import JuegoDetectado, ParametrosRadar


class Command(BaseCommand):
    help = (
        'Revisa los juegos publicados por el radar y avisa de los que quedaron sin ninguna '
        'variante comprable. Con --reparar intenta volver a publicarlos.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--reparar', action='store_true',
            help='Vuelve a publicar los que se puedan arreglar con la configuracion actual.',
        )
        parser.add_argument(
            '--retirar', action='store_true',
            help='Deja en stock 0 los que sigan sin arreglo, para que no aparezcan en la tienda.',
        )

    def handle(self, *args, **options):
        parametros = ParametrosRadar.actuales()
        self._mostrar_configuracion(parametros)

        publicados = list(JuegoDetectado.objects.filter(estado='publicado')
                          .exclude(producto_publicado_id=None)
                          .prefetch_related('precios'))
        if not publicados:
            self.stdout.write('No hay ningun juego publicado por el radar.')
            return

        # Una promocion ya vencida tambien se ve "sin variantes comprables",
        # porque radar_vencer deja las variantes en stock 0. Republicarla les
        # devolveria el stock y dejaria el juego a la venta al precio de una
        # oferta que ya no existe: cada venta a perdida. Esas no se tocan.
        ahora = timezone.now()
        vencidos = [j for j in publicados if j.vence and j.vence < ahora]
        rotos = [j for j in publicados
                 if j not in vencidos and j.variantes_vendibles() == 0]
        if vencidos:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                '%s con la promocion ya vencida: no se tocan aqui, los retira '
                'radar_vencer.' % len(vencidos)))

        self.stdout.write('')
        self.stdout.write('Publicados: %s. Sin ninguna variante comprable: %s.'
                          % (len(publicados), len(rotos)))
        if not rotos:
            self.stdout.write(self.style.SUCCESS('Todo lo publicado se puede comprar.'))
            return

        arreglados, sin_arreglo = [], []
        for juego in rotos:
            etiqueta = '  #%s %s (producto %s)' % (
                juego.pk, juego.titulo[:50], juego.producto_publicado_id)
            if not options['reparar']:
                self.stdout.write(etiqueta)
                continue
            try:
                juego.publicar(parametros)
            except ValueError as exc:
                sin_arreglo.append((juego, str(exc)))
                self.stdout.write('%s -> %s' % (etiqueta, exc))
                continue
            if juego.variantes_vendibles() == 0:
                sin_arreglo.append((juego, 'se republico pero sigue sin variantes comprables'))
                self.stdout.write('%s -> sigue sin variantes' % etiqueta)
            else:
                arreglados.append(juego)
                self.stdout.write(self.style.SUCCESS('%s -> arreglado' % etiqueta))

        if not options['reparar']:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'Solo diagnostico. Para intentar arreglarlos: '
                'manage.py radar_revisar --reparar'))
            return

        if options['retirar'] and sin_arreglo:
            for juego, _motivo in sin_arreglo:
                juego.despublicar()
            self.stdout.write('Retirados de la tienda (stock 0): %s' % len(sin_arreglo))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Arreglados: %s' % len(arreglados)))
        if sin_arreglo:
            self.stdout.write(self.style.ERROR(
                'Siguen rotos: %s. Arriba esta el motivo de cada uno; casi siempre es algo '
                'que falta en Parametros del radar.' % len(sin_arreglo)))
            if not options['retirar']:
                self.stdout.write(
                    'Para sacarlos de la tienda mientras tanto: '
                    'manage.py radar_revisar --reparar --retirar')

    def _mostrar_configuracion(self, parametros):
        """La causa casi siempre esta aqui, asi que se imprime siempre."""
        self.stdout.write('Parametros del radar:')
        for etiqueta, valor in (
            ('licencia por defecto (codigo)', parametros.licencia_default),
            ('licencia primaria', parametros.licencia_primaria),
            ('licencia secundaria', parametros.licencia_secundaria),
            ('tipo de producto', parametros.tipo_producto),
            ('consola Xbox por defecto', parametros.consola_xbox),
            ('consola PlayStation por defecto', parametros.consola_ps),
            ('stock de publicacion', parametros.stock_publicacion),
        ):
            if valor in (None, ''):
                self.stdout.write(self.style.WARNING('  %-32s SIN CONFIGURAR' % etiqueta))
            else:
                self.stdout.write('  %-32s %s' % (etiqueta, valor))
