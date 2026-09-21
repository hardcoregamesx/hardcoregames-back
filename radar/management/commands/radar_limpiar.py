# -*- coding: utf-8 -*-
"""Borra del catalogo los productos del radar que vencieron sin venderse nunca.

Sin esto, cada ciclo dejaria decenas de productos muertos en el catalogo: la
promocion ya no existe, nadie los compro, y aun asi aparecen en el buscador y
en las categorias. Son promociones de dos o tres dias, asi que se acumulan
rapido.

Solo borra lo que cumple TODO esto:
  - lo publico el radar (sobre_pedido = True),
  - su promocion ya vencio,
  - nunca se vendio (ni una linea de venta, ni un plan de pago, ni esta en el
    carrito de nadie).

Si alguna vez se vendio, el producto se queda para siempre: esta en el
historial del cliente y borrarlo dejaria una venta huerfana.

    docker exec hc-django python manage.py radar_limpiar
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from radar.models import JuegoDetectado


class Command(BaseCommand):
    help = (
        'Borra los productos publicados por el radar cuya promocion vencio y que nunca se '
        'vendieron. Los que tuvieron al menos una venta NO se tocan.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dias', type=int, default=3,
            help='Cuantos dias esperar tras el vencimiento antes de borrar (default 3).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Muestra que se borraria, sin borrar.',
        )

    def handle(self, *args, **options):
        from products.models import GameDetail, PaymentPlan, Products, SaleDetail, ShoppingCar

        limite = timezone.now() - timezone.timedelta(days=options['dias'])
        candidatos = (JuegoDetectado.objects
                      .filter(estado__in=['publicado', 'vencido'])
                      .exclude(producto_publicado_id=None)
                      .prefetch_related('precios'))

        borrados, conservados = 0, 0
        for juego in candidatos:
            if not juego.vence or juego.vence > limite:
                continue

            pid = juego.producto_publicado_id
            # Ojo con los nombres: en SaleDetail la variante se llama
            # `combinacion`, y en ShoppingCar el campo `producto` apunta a
            # GameDetail, no a Products.
            variantes = list(
                GameDetail.objects.filter(producto_id=pid).values_list('id_game_detail', flat=True))

            vendido = (
                SaleDetail.objects.filter(producto_id=pid).exists()
                or SaleDetail.objects.filter(combinacion_id__in=variantes).exists()
                or ShoppingCar.objects.filter(producto_id__in=variantes).exists()
                or PaymentPlan.objects.filter(gamedetail_id__in=variantes).exists()
            )
            if vendido:
                conservados += 1
                continue

            self.stdout.write('  borrar: [%s] %s' % (pid, juego.titulo))
            if not options['dry_run']:
                with transaction.atomic():
                    GameDetail.objects.filter(producto_id=pid).delete()
                    Products.objects.filter(id_product=pid).delete()
                    juego.producto_publicado_id = None
                    juego.estado = 'vencido'
                    juego.save(update_fields=['producto_publicado_id', 'estado'])
            borrados += 1

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                'Modo --dry-run: no se borro nada. Se borrarian %s.' % borrados))
        else:
            self.stdout.write(self.style.SUCCESS('Productos borrados del catalogo: %s' % borrados))
        if conservados:
            self.stdout.write(
                '%s se conservan porque tuvieron ventas o estan en algun carrito.' % conservados)
