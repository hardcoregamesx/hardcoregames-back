# -*- coding: utf-8 -*-
"""Retira de la tienda las ofertas cuya promocion ya vencio.

Las ofertas entran cuando el radar las detecta y salen solas cuando el
proveedor termina la promocion: esa fecha la da la propia tienda, no se
inventa. Sin esto quedarian publicados juegos a un precio que ya no se puede
conseguir, y cada venta seria a perdida.

Pensado para correr varias veces al dia:
    docker exec hc-django python manage.py radar_vencer
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from radar.models import Combo, JuegoDetectado


class Command(BaseCommand):
    help = (
        'Deja en stock 0 los productos publicados por el radar cuya promocion ya vencio. '
        'No borra nada: el producto puede estar en el historial de una venta.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Muestra que se retiraria, sin escribir.',
        )

    def handle(self, *args, **options):
        ahora = timezone.now()
        publicados = list(JuegoDetectado.objects
                          .filter(estado='publicado')
                          .prefetch_related('precios'))
        # Un combo cae con la PRIMERA de sus promociones (Combo.vence), porque
        # su precio se armo contando ese juego barato.
        publicados += list(Combo.objects
                           .filter(estado='publicado')
                           .prefetch_related('items__juego__precios'))

        vencidos = [j for j in publicados if j.vence and j.vence < ahora]

        if not vencidos:
            self.stdout.write('Nada que retirar: ninguna promocion publicada ha vencido.')
            return

        for item in vencidos:
            self.stdout.write('  %s (vencio %s)' % (item, item.vence.strftime('%d/%m/%Y')))
            if not options['dry_run']:
                item.despublicar()

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                'Modo --dry-run: no se escribio nada. Se retirarian %s.' % len(vencidos)))
        else:
            self.stdout.write(self.style.SUCCESS('Retirados de la tienda: %s' % len(vencidos)))
