from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from products.models import Coupon, CouponPurgeLog, CouponRedemption


class Command(BaseCommand):
    help = (
        'Borra cupones vencidos que nunca se usaron. Antes de borrar, suma su '
        'conteo a CouponPurgeLog (por source + mes de created_at) para no '
        'perder el histórico de "generados vs usados".'
    )

    def handle(self, *args, **options):
        now = timezone.now()
        expired_unused = Coupon.objects.filter(expiration_date__lt=now).exclude(
            id_coupon__in=CouponRedemption.objects.values('coupon_id')
        )

        buckets = {}
        for source, created_at in expired_unused.values_list('source', 'created_at'):
            key = (source, created_at.strftime('%Y-%m'))
            buckets[key] = buckets.get(key, 0) + 1

        if not buckets:
            self.stdout.write('No hay cupones vencidos sin usar para purgar.')
            return

        with transaction.atomic():
            for (source, period), count in buckets.items():
                log, _ = CouponPurgeLog.objects.get_or_create(source=source, period=period)
                CouponPurgeLog.objects.filter(pk=log.pk).update(count=F('count') + count)

            deleted_count, _ = expired_unused.delete()

        self.stdout.write(self.style.SUCCESS(f'Purgados {deleted_count} cupones vencidos sin usar.'))
