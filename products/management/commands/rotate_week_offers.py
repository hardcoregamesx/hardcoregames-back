import random

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F

from products.models import GameDetail, Products


class Command(BaseCommand):
    help = (
        'Rotación semanal de "Oferta de la semana": elige productos al azar y marca '
        'Products.oferta_semana=True en ellos, desmarcando el resto. Prioriza productos '
        'con un descuento real ya configurado (GameDetail.precio_descuento < precio, '
        'stock > 0); si no hay suficientes, completa con productos en stock sin descuento. '
        'Pensado para correr cada domingo 00:00 hora Colombia (05:00 UTC), el mismo corte '
        'que muestra el contador regresivo de /week-offers.'
    )

    DEFAULT_COUNT = 12

    def add_arguments(self, parser):
        parser.add_argument(
            '--count', type=int, default=self.DEFAULT_COUNT,
            help=f'Cuántos productos dejar marcados como oferta de la semana (default {self.DEFAULT_COUNT}).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Muestra qué productos se elegirían, sin escribir cambios.',
        )

    def handle(self, *args, **options):
        count = options['count']
        dry_run = options['dry_run']

        discounted_ids = list(
            GameDetail.objects.filter(stock__gt=0, precio_descuento__gt=0)
            .exclude(precio_descuento__gte=F('precio'))
            .values_list('producto_id', flat=True)
            .distinct()
        )
        random.shuffle(discounted_ids)
        chosen = discounted_ids[:count]

        if len(chosen) < count:
            fallback_ids = list(
                GameDetail.objects.filter(stock__gt=0, precio__gt=0)
                .exclude(producto_id__in=chosen)
                .values_list('producto_id', flat=True)
                .distinct()
            )
            random.shuffle(fallback_ids)
            chosen += fallback_ids[: count - len(chosen)]

        chosen = chosen[:count]

        if not chosen:
            self.stdout.write(self.style.WARNING('No hay productos con stock disponibles para elegir.'))
            return

        if dry_run:
            titles = Products.objects.filter(id_product__in=chosen).values_list('id_product', 'title')
            self.stdout.write(f'Se elegirían {len(chosen)} productos (con --dry-run, sin escribir cambios):')
            for pid, title in titles:
                self.stdout.write(f'  - [{pid}] {title}')
            return

        with transaction.atomic():
            Products.objects.filter(oferta_semana=True).exclude(id_product__in=chosen).update(oferta_semana=False)
            Products.objects.filter(id_product__in=chosen).update(oferta_semana=True)

        self.stdout.write(self.style.SUCCESS(f'Oferta de la semana actualizada: {len(chosen)} productos marcados.'))
