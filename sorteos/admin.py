import random
from datetime import datetime, timezone

from django.contrib import admin, messages
from django.db.models import Count, Sum

from .models import Sorteo, SorteoOrderBuy, SorteoWinner


class SorteoWinnerInline(admin.TabularInline):
    model = SorteoWinner
    extra = 0
    fields = ('user', 'drawn_at')
    readonly_fields = ('user', 'drawn_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        # Los ganadores solo se crean via la accion "Ejecutar sorteo".
        return False


def _qualifies(purchases_count, amount_sum, sorteo):
    has_count_req = sorteo.min_purchases is not None
    has_amount_req = sorteo.min_amount is not None
    count_ok = (not has_count_req) or purchases_count >= sorteo.min_purchases
    amount_ok = (not has_amount_req) or (amount_sum or 0) >= sorteo.min_amount

    if has_count_req and has_amount_req:
        return (count_ok and amount_ok) if sorteo.require_both else (count_ok or amount_ok)
    return count_ok and amount_ok


@admin.action(description='Ejecutar sorteo (elige ganadores al azar)')
def ejecutar_sorteo(modeladmin, request, queryset):
    for sorteo in queryset:
        if sorteo.status == 'FINISHED':
            modeladmin.message_user(
                request, f'"{sorteo}" ya fue ejecutado, se omite.', level=messages.WARNING,
            )
            continue

        rows = (
            SorteoOrderBuy.objects
            .filter(status='completed', created_at__gte=sorteo.start_date, created_at__lte=sorteo.end_date)
            .values('user_id')
            .annotate(purchases_count=Count('id_order'), amount_sum=Sum('amount'))
        )

        qualified_user_ids = [
            row['user_id'] for row in rows
            if _qualifies(row['purchases_count'], row['amount_sum'], sorteo)
        ]

        if not qualified_user_ids:
            modeladmin.message_user(
                request, f'"{sorteo}": nadie califica todavía, no se eligió ningún ganador.',
                level=messages.WARNING,
            )
            continue

        winners_count = min(sorteo.winners_count, len(qualified_user_ids))
        chosen = random.sample(qualified_user_ids, winners_count)

        now = datetime.now(timezone.utc)
        SorteoWinner.objects.bulk_create([
            SorteoWinner(sorteo=sorteo, user_id=user_id, drawn_at=now)
            for user_id in chosen
        ])

        sorteo.status = 'FINISHED'
        sorteo.save(update_fields=['status'])

        modeladmin.message_user(
            request, f'"{sorteo}": {len(chosen)} ganador(es) elegido(s) entre {len(qualified_user_ids)} calificados.',
            level=messages.SUCCESS,
        )


@admin.register(Sorteo)
class SorteoAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'start_date', 'end_date', 'min_purchases', 'min_amount', 'require_both', 'winners_count')
    list_filter = ('status',)
    search_fields = ('title', 'legend')
    date_hierarchy = 'start_date'
    inlines = [SorteoWinnerInline]
    actions = [ejecutar_sorteo]
    fields = (
        'title', 'legend', 'prize_image_url', 'start_date', 'end_date',
        'min_purchases', 'min_amount', 'require_both', 'winners_count', 'status',
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_at = datetime.now(timezone.utc)
        super().save_model(request, obj, form, change)


@admin.register(SorteoWinner)
class SorteoWinnerAdmin(admin.ModelAdmin):
    list_display = ('sorteo', 'user', 'drawn_at')
    list_filter = ('sorteo',)
    search_fields = ('user__username', 'user__email')
    date_hierarchy = 'drawn_at'

    def has_add_permission(self, request):
        # Los ganadores solo los crea la accion "Ejecutar sorteo".
        return False

    def has_change_permission(self, request, obj=None):
        return False
