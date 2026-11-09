from django.core.management.base import BaseCommand

from products import referrals


class Command(BaseCommand):
    help = 'Libera al saldo el cashback de referidos cuya retención de 3 días ya terminó (cron cada 10 min).'

    def handle(self, *args, **options):
        n = referrals.release_due()
        self.stdout.write(f'cashback liberado: {n}')
