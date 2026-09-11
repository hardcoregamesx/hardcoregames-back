from datetime import date, timedelta

from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.shortcuts import render
from django.urls import reverse
from django.utils.html import format_html

from .models import JuegoPorVencer, PointTransaction, Roulette, RoulettePrize, RouletteSpin


class RoulettePrizeInline(admin.TabularInline):
    model = RoulettePrize
    extra = 1
    fields = (
        'name', 'prize_type', 'value', 'weight', 'coupon_validity_minutes',
        'min_purchase', 'max_per_user', 'stock', 'color', 'display_order', 'is_active',
    )


@admin.register(Roulette)
class RouletteAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'requires_membership', 'cost_points', 'max_spins_per_day', 'max_spins_per_month', 'created_at')
    list_filter = ('is_active', 'requires_membership')
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


class DiasParaVencerFilter(admin.SimpleListFilter):
    title = 'días para vencer'
    parameter_name = 'dias'

    def lookups(self, request, model_admin):
        return [('7', 'en 7 días'), ('15', 'en 15 días'), ('30', 'en 30 días')]

    def queryset(self, request, queryset):
        if self.value():
            limite = date.today() + timedelta(days=int(self.value()))
            return queryset.filter(fecha_vencimiento__lte=limite)


@admin.action(description='Renovar (extender fecha de vencimiento)')
def renovar_suscripcion(modeladmin, request, queryset):
    if queryset.count() != 1:
        modeladmin.message_user(
            request, 'Selecciona una sola fila para renovar a la vez.', level=messages.WARNING,
        )
        return None

    obj = queryset.first()
    today = date.today()
    dias_originales = obj.combinacion.duracion_dias_alquiler if obj.combinacion else None
    base = obj.fecha_vencimiento if obj.fecha_vencimiento and obj.fecha_vencimiento > today else today
    fecha_sugerida = base + timedelta(days=dias_originales) if dias_originales else None

    if 'apply' in request.POST:
        nueva_fecha_str = request.POST.get('nueva_fecha_vencimiento')
        try:
            nueva_fecha = date.fromisoformat(nueva_fecha_str)
        except (TypeError, ValueError):
            modeladmin.message_user(request, 'Fecha inválida.', level=messages.ERROR)
            return None
        obj.fecha_vencimiento = nueva_fecha
        obj.save(update_fields=['fecha_vencimiento'])
        modeladmin.message_user(
            request,
            f'"{obj.producto.title}" renovado. Nuevo vencimiento: {nueva_fecha:%d/%m/%Y}.',
            level=messages.SUCCESS,
        )
        return None

    context = {
        **modeladmin.admin_site.each_context(request),
        'title': 'Renovar suscripción',
        'object': obj,
        'dias_originales': dias_originales,
        'fecha_actual': obj.fecha_vencimiento,
        'fecha_sugerida': fecha_sugerida,
        'opts': modeladmin.model._meta,
        'action_checkbox_name': ACTION_CHECKBOX_NAME,
    }
    return render(request, 'admin/rewards/juegoporvencer/renovar_confirmation.html', context)


@admin.register(JuegoPorVencer)
class JuegoPorVencerAdmin(admin.ModelAdmin):
    list_display = (
        'producto_link', 'genero', 'fecha_venta', 'fecha_vencimiento',
        'dias_restantes', 'usuario_email', 'cuenta_link',
    )
    list_filter = (DiasParaVencerFilter,)
    search_fields = ('producto__title', 'usuario__email', 'usuario__username')
    actions = [renovar_suscripcion]
    list_per_page = 25

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'producto', 'producto__tipo_juego', 'usuario', 'combinacion', 'cuenta',
        )

    @admin.display(description='Producto', ordering='producto__title')
    def producto_link(self, obj):
        url = reverse('admin:products_products_change', args=[obj.producto.id_product])
        return format_html('<a href="{}">{}</a>', url, obj.producto.title)

    @admin.display(description='Género')
    def genero(self, obj):
        return obj.producto.tipo_juego.descripcion if obj.producto.tipo_juego else '—'

    @admin.display(description='Días restantes', ordering='fecha_vencimiento')
    def dias_restantes(self, obj):
        dias = (obj.fecha_vencimiento - date.today()).days
        color = '#e5484d' if dias <= 7 else ('#d9a91b' if dias <= 15 else '#2b2a3a')
        return format_html('<b style="color:{}">{} días</b>', color, dias)

    @admin.display(description='Usuario')
    def usuario_email(self, obj):
        return obj.usuario.email if obj.usuario else '—'

    @admin.display(description='Cuenta')
    def cuenta_link(self, obj):
        if not obj.cuenta:
            return '—'
        url = reverse('admin:products_productaccounts_change', args=[obj.cuenta.id_product_accounts])
        return format_html('<a href="{}">{}</a>', url, obj.cuenta.cuenta)
