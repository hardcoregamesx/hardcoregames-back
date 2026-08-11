from django.contrib import admin

from .models import PointTransaction, Roulette, RoulettePrize, RouletteSpin


class RoulettePrizeInline(admin.TabularInline):
    model = RoulettePrize
    extra = 1
    fields = (
        'name', 'prize_type', 'value', 'weight', 'coupon_validity_minutes',
        'min_purchase', 'max_per_user', 'stock', 'color', 'display_order', 'is_active',
    )


@admin.register(Roulette)
class RouletteAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'cost_points', 'max_spins_per_day', 'created_at')
    list_filter = ('is_active',)
    inlines = [RoulettePrizeInline]


@admin.register(RoulettePrize)
class RoulettePrizeAdmin(admin.ModelAdmin):
    list_display = ('name', 'roulette', 'prize_type', 'value', 'weight', 'stock', 'is_active', 'display_order')
    list_filter = ('roulette', 'prize_type', 'is_active')
    ordering = ('roulette', 'display_order')


@admin.register(RouletteSpin)
class RouletteSpinAdmin(admin.ModelAdmin):
    list_display = ('user', 'roulette', 'prize', 'points_spent', 'coupon', 'created_at')
    list_filter = ('roulette', 'prize')
    search_fields = ('user__username', 'user__email', 'idempotency_key')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        # Los giros solo los crea el backend de la ruleta, nunca a mano.
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PointTransaction)
class PointTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'delta', 'balance_after', 'reason', 'reference_type', 'created_at')
    list_filter = ('reason',)
    search_fields = ('user__username', 'user__email', 'description')
    date_hierarchy = 'created_at'

    def has_change_permission(self, request, obj=None):
        # El ledger es un registro de auditoria: no se edita, solo se crea
        # (via un ajuste administrativo) o se consulta.
        return False
