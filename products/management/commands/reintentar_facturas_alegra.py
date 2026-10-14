from django.core.management.base import BaseCommand

from products import alegra


class Command(BaseCommand):
    help = (
        'Reintenta las facturas electrónicas de Alegra que quedaron pendientes '
        '(Alegra caído, error transitorio). Pensado para el cron, cada 5-10 min.'
    )

    def handle(self, *args, **options):
        if not alegra.enabled():
            self.stdout.write('Alegra apagado (ALEGRA_ENABLED / ALEGRA_TOKEN). Nada que hacer.')
            return
        self.stdout.write(f'Facturas reintentadas: {alegra.reintentar_pendientes()}')
