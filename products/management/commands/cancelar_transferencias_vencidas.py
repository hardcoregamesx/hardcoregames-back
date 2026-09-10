from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from products.models import Transactions
from products.views import TRANSFERENCIA_PAYMENT_ID, _notify_transferencia_cancelada


class Command(BaseCommand):
    help = (
        'Respaldo del vencimiento de pedidos por transferencia Bre-B: pagos-nequi ya '
        'avisa por webhook cuando un pedido vence (10min sin "Ya transferí", 30min sin '
        'match, 24h en baja confianza), pero si esa llamada falla (red caída, etc.) el '
        'pedido quedaría pendiente para siempre. Este comando cancela cualquier '
        'transacción de transferencia que siga "pendiente" más de 26h después de creada '
        '(margen sobre el plazo máximo real de 24h) y avisa al cliente por correo -- '
        'mismo criterio que process_transferencia_event(confidence="vencida").'
    )

    SAFETY_MARGIN_HOURS = 26

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=self.SAFETY_MARGIN_HOURS)
        vencidas = Transactions.objects.filter(
            payment_id=TRANSFERENCIA_PAYMENT_ID, status="pendiente", date_transaction__lt=cutoff,
        )

        count = 0
        for transaction in vencidas:
            transaction.status = "cancelada"
            transaction.save()
            _notify_transferencia_cancelada(transaction)
            count += 1

        if count:
            self.stdout.write(self.style.SUCCESS(
                f'Canceladas {count} transacción(es) de transferencia huérfanas (webhook de '
                f'vencimiento nunca llegó).'
            ))
        else:
            self.stdout.write('No hay transferencias pendientes vencidas por respaldar.')
