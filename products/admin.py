import glob
import os
from datetime import date, timedelta
import threading
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin import SimpleListFilter
from django.core.cache import cache
from django import forms
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils.html import format_html
from django.shortcuts import redirect

from products.accountProductForm import AccountProductForm, FileForm
from products.formProducts import ProductsFormCreate
from products.managePriceFile import ManegePricesFile
from products.models import Products, ProductsType, SaleDetail, ProductAccounts, Files, GameDetail, Consoles, \
    TypeGames, VariablesSistema, Licenses, TypeAccounts, Coupon, CouponRule, CouponRedemption, ProductoDestacado, \
    GameDetailInventario, ProductAlias, CouponPurgeLog
from django.contrib.admin import DateFieldListFilter
from products.UpdateProductForm import UpdateProductForm
@admin.action(description="Update price and other fields")
def update_game_detail(admin_model, request, queryset):
    if 'apply' in request.POST:
        product = request.POST.get('producto')
        console = request.POST.get('consola')
        licencia = request.POST.get('licencia')
        new_price = request.POST.get('precio')

        # Filter and update the GameDetail objects based on producto, consola, and licencia
        game_details = queryset.filter(
            producto=product,
            consola=console,
            licencia=licencia
        )

        updated_count = game_details.update(
            precio=new_price,
        )
        messages.success(request, f"Successfully updated {updated_count} game details.")
        return None


class CloseToExp(SimpleListFilter):
    title = "proximos a vencer"  # a label for our filter
    parameter_name = "days"  # you can put anything here

    def lookups(self, request, model_admin):
        return [
            ("5", "5 dias"),
            ("15", "15 dias"),
        ]

    def queryset(self, request, queryset):
        if self.value():
            today = date.today()
            return queryset.filter(fecha_vencimiento__range=(today, today + timedelta(days=int(self.value()))))


class ProductsAdminForm(forms.ModelForm):
    alias = forms.CharField(
        required=False,
        label='Alias',
        help_text='Nombres alternativos del producto, separados por comas. Ej: GTA 5, GTA V, Grand Theft Auto 5',
        widget=forms.TextInput(attrs={'size': 100}),
    )

    class Meta:
        model = Products
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            existentes = ProductAlias.objects.filter(producto=self.instance).values_list('alias', flat=True)
            self.fields['alias'].initial = ', '.join(existentes)


class ProductsAdmin(admin.ModelAdmin):
    form = ProductsAdminForm


    list_display = ('id_product','title','stock_primaries', 'price_primaries',
                    'stock_secondaries', 'price_secondaries',
                    'stock_codes', 'price_codes',
                    'stock_pc', 'price_pc', 'console', 'duration_days')

    @staticmethod
    def product_id(obj):
        price_codes = (
            GameDetail.objects.filter(
                licencia__id_license=1,
                producto__id_product=obj.id_product,
                stock__gt = 0
            )
            .first())
        return price_codes.id_game_detail if price_codes is not None else None

    @staticmethod
    def stock_primaries(obj):
        return (
                GameDetail.objects.filter(
                    licencia__id_license=1,
                    producto__id_product=obj.id_product,
                    stock__gt = 0
                )
                .aggregate(total_stock=Sum('stock'))['total_stock'] or 0)

    @staticmethod
    def stock_secondaries(obj):
        return (
                GameDetail.objects.filter(
                    licencia__id_license=2,
                    producto__id_product=obj.id_product,
                    stock__gt = 0
                )
                .aggregate(total_stock=Sum('stock'))['total_stock'] or 0
        )

    @staticmethod
    def stock_codes(obj):
        return (
                GameDetail.objects.filter(
                    licencia__id_license=3,
                    producto__id_product=obj.id_product
                )
                .aggregate(total_stock=Sum('stock'))['total_stock'] or 0
        )


    @staticmethod
    def stock_pc(obj):
        return (
                GameDetail.objects.filter(
                    licencia__id_license=4,
                    producto__id_product=obj.id_product,
                )
                .aggregate(total_stock=Sum('stock'))['total_stock'] or 0
        )

    @staticmethod
    def price_primaries(obj):
        inventory_primary = (
            GameDetail.objects.filter(
                licencia__id_license=1,
                producto__id_product=obj.id_product
            ).first()
        )
        if inventory_primary is None:
            return None
        url = f"/admin/products/gamedetail/{inventory_primary.id_game_detail}/change/"
        return format_html(
            '<a href="{}" target="_blank">{}</a>',
            url,
            inventory_primary.precio
        )

    @staticmethod
    def price_secondaries(obj):
        inventory_secondary = (
            GameDetail.objects.filter(
                licencia__id_license=2,
                producto__id_product=obj.id_product
            ).first()
        )
        if inventory_secondary is None:
            return None
        url = f"/admin/products/gamedetail/{inventory_secondary.id_game_detail}/change/"
        return format_html(
            '<a href="{}" target="_blank">{}</a>',
            url,
            inventory_secondary.precio
        )
    @staticmethod
    def price_codes(obj):
        inventory_codes = (
            GameDetail.objects.filter(
                licencia__id_license=3,
                producto__id_product=obj.id_product
            ).first()
        )
        if inventory_codes is None:
            return None
        url = f"/admin/products/gamedetail/{inventory_codes.id_game_detail}/change/"
        return format_html(
            '<a href="{}" target="_blank">{}</a>',
            url,
            inventory_codes.precio
        )

    @staticmethod
    def price_pc(obj):
        inventory_pc = (
            GameDetail.objects.filter(
                licencia__id_license=4,
                producto__id_product=obj.id_product
            ).first()
        )
        if inventory_pc is None:
            return None
        url = f"/admin/products/gamedetail/{inventory_pc.id_game_detail}/change/"
        return format_html(
            '<a href="{}" target="_blank">{}</a>',
            url,
            inventory_pc.precio
        )

    @staticmethod
    def console(obj):
        game_inventory = (
            GameDetail.objects.filter(
                producto__id_product=obj.id_product
            ).distinct('consola')
        )
        return ", ".join(str(result.consola) for result in game_inventory) \
            if game_inventory is not None else None

    @staticmethod
    def duration_days(obj):
        game_inventory = (
            GameDetail.objects.filter(
                producto__id_product=obj.id_product
            ).distinct('duracion_dias_alquiler')
        )
        return ", ".join(str(result.duracion_dias_alquiler) for result in game_inventory) \
            if game_inventory is not None else None
    list_per_page = 15
    search_fields = ['title',]
    list_filter = ["consola",]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        raw = form.cleaned_data.get('alias', '') if hasattr(form, 'cleaned_data') else ''
        aliases_nuevos = set(a.strip() for a in raw.split(',') if a.strip())

        existentes_qs = ProductAlias.objects.filter(producto=obj)
        aliases_existentes = set(existentes_qs.values_list('alias', flat=True))

        a_borrar = aliases_existentes - aliases_nuevos
        if a_borrar:
            existentes_qs.filter(alias__in=a_borrar).delete()

        a_crear = aliases_nuevos - aliases_existentes
        for alias_texto in a_crear:
            ProductAlias.objects.create(producto=obj, alias=alias_texto)

class PaymentAdmin(admin.ModelAdmin):
    list_display = ['pk', 'description']


class ProductsTypeAdmin(admin.ModelAdmin):
    list_display = ['pk', 'description']


class ConsolesAdmin(admin.ModelAdmin):
    list_display = ['pk', 'descripcion', 'estado']
    search_fields = ['producto__title',]

class TypeGamesAdmin(admin.ModelAdmin):
    list_display = ['id_type_game', 'descripcion']


class TypeAccountsAdmin(admin.ModelAdmin):
    list_display = ['id_type_account', 'descripcion']


class LicencesAdmin(admin.ModelAdmin):
    list_display = ['id_license', 'descripcion']

class GameDetailAdmin(admin.ModelAdmin):
    @staticmethod
    def has_module_permission(request):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('producto', 'consola', 'licencia', 'cuenta')

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        queryset = queryset.filter(stock__gt=0, precio__gt=0,)
        return queryset, use_distinct

    def product(obj):
        url = reverse('admin:products_products_change', args=[obj.producto.id_product])
        return format_html(u'<a href="{}" style="margin-right:100px">{}</a>',
                           url, obj.producto.title)

    @staticmethod
    def save_model(request, obj, form, change):
        product = int(request.POST.get('producto'))
        license = int(request.POST.get('licencia'))
        duration_days = int(request.POST.get('duracion_dias_alquiler'))

        game_details = GameDetail.objects.filter(
            producto=product,
            licencia=license,
            duracion_dias_alquiler=duration_days
        )

        update_fields = {}
        new_price = request.POST.get('precio')
        price_off = request.POST.get('precio_descuento')
        if new_price:
            update_fields['precio'] = new_price
        if price_off:
            update_fields['precio_descuento'] = price_off
        if update_fields:
            game_details.update(**update_fields)

        cache.clear()
        messages.success(request, f"Successfully updated game details.")
        return

    @staticmethod
    def response_change(request, obj):
        return redirect('/admin/products/products/')

    @admin.display(description='Nombre de cuenta')
    def account_name(self, obj):
        if obj.cuenta:
            url = reverse('admin:products_productaccounts_change', args=[obj.cuenta.id_product_accounts])
            return format_html('<a href="{}" target="_blank">{}</a>', url, obj.cuenta.cuenta)
        return '—'

    @admin.display(description='Contraseña')
    def account_password(self, obj):
        if obj.cuenta and obj.cuenta.password:
            return obj.cuenta.password
        return '—'

    @admin.display(description='Stock disponible')
    def account_stock(self, obj):
        return obj.stock

    product.short_description = 'Producto'
    search_fields = ['producto__title', 'producto__id_product', 'cuenta__cuenta']
    list_filter = ["consola", 'licencia']
    form = UpdateProductForm
    list_display = ('consola', 'licencia', 'precio')
    actions = [update_game_detail]
    list_per_page = 10
    readonly_fields = ('account_name', 'account_password', 'account_stock')
    fieldsets = (
        (None, {
            'fields': ('producto', 'licencia', 'precio', 'precio_descuento', 'duracion_dias_alquiler'),
        }),
        ('Información de Cuenta', {
            'fields': ('account_name', 'account_password', 'account_stock'),
            'description': 'Datos de la cuenta asociada a este GameDetail.',
        }),
    )

class SalesAdmin(admin.ModelAdmin):
    list_display = ['id_sale', 'date_sale', 'status_sale', 'amount', 'status_sale', 'payment_id', 'user_id']


class FilesAdmin(admin.ModelAdmin):
    list_display = ['archivo', 'procesado', 'resultado_corto']
    readonly_fields = ['procesado', 'resultado']
    form = FileForm

    def resultado_corto(self, obj):
        if not obj.resultado:
            return '-'
        return (obj.resultado[:120] + '...') if len(obj.resultado) > 120 else obj.resultado
    resultado_corto.short_description = 'Resultado'

    def save_model(self, request, obj, form, change):
        for filename in glob.glob(settings.STATIC_URL_FILES + '*.xlsx'):
            os.remove(filename)
        Files.objects.all().delete()
        super().save_model(request, obj, form, change)

        threading.Thread(target=ManegePricesFile, kwargs={'files_id': obj.pk}, daemon=True).start()

        self.message_user(
            request,
            "El archivo fue subido. El procesamiento se está ejecutando en segundo plano. "
            "Actualiza esta lista en unos segundos para ver el resultado (cuántas cuentas se crearon y si hubo errores)."
        )
class SystemVariablesAdmin(admin.ModelAdmin):
    list_display = ['nombre_variable', 'descripcion', 'valor', 'url', 'estado']


class GameDetailStockInline(admin.TabularInline):
    """
    Muestra, dentro de cada cuenta, todas sus combinaciones de
    producto/licencia/consola con el stock editable en línea — para no
    tener que ir a la base de datos a averiguar qué cuenta tiene stock
    disponible antes de una venta manual.
    """
    model = GameDetail
    fk_name = 'cuenta'
    extra = 0
    can_delete = False
    fields = ('col_producto', 'col_licencia', 'col_consola', 'precio', 'stock')
    readonly_fields = ('col_producto', 'col_licencia', 'col_consola', 'precio')
    verbose_name = 'combinación de stock'
    verbose_name_plural = 'Stock por combinación (producto / licencia / consola)'

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description='Producto')
    def col_producto(self, obj):
        return obj.producto.title if obj.producto else '—'

    @admin.display(description='Licencia')
    def col_licencia(self, obj):
        return str(obj.licencia) if obj.licencia else '—'

    @admin.display(description='Consola')
    def col_consola(self, obj):
        return obj.consola or '—'


class ProductAccountsAdmin(admin.ModelAdmin):
    list_display = ['cuenta', 'password', 'activa', 'tipo_cuenta', 'dias_duracion', 'codigo_seguridad', 'stock_total']
    form = AccountProductForm
    search_fields = ['cuenta',]
    list_filter = ["tipo_cuenta",]
    list_per_page = 10
    inlines = [GameDetailStockInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_stock_total=Sum('gamedetail__stock'))

    @admin.display(description='Stock total', ordering='_stock_total')
    def stock_total(self, obj):
        total = obj._stock_total or 0
        color = '#c62828' if total == 0 else '#2e7d32'
        return format_html('<span style="color:{};font-weight:bold;">{}</span>', color, total)

class SalesDetailAdmin(admin.ModelAdmin):
    def producto(obj):
        url = reverse('admin:products_products_change', args=[obj.producto.id_product])
        return format_html(u'<a href="{}" style="margin-right:100px">{}</a>',
                           url, obj.producto.title)

    def cuenta(obj):
        url = reverse('admin:products_productaccounts_change', args=[obj.cuenta.id_product_accounts])
        return format_html(u'<a href="{}" style="margin-right:100px">{}</a>',
                           url, obj.cuenta.cuenta)

    def password(self, obj):
        return obj.cuenta.password

    list_display = ["pk", producto, "combinacion", "fecha_venta", "fecha_vencimiento", cuenta,
                    "password", "usuario"]
    list_filter = [CloseToExp, ("fecha_venta", DateFieldListFilter),]

    @admin.action(description='Enviar mensaje de renovación')
    def send_email_renovation(self, request, queryset):
        for sale in queryset:
            print(sale)
        messages.add_message(request, messages.INFO, 'Mensaje enviado exitosamente')

    actions = [send_email_renovation]
    search_fields = ["usuario__email", "fecha_venta"]
    list_per_page = 10

admin.site.site_header = 'Administración HardCoreGames'
# Register your models here.
admin.site.register(Products, ProductsAdmin)
admin.site.register(ProductsType, ProductsTypeAdmin)
admin.site.register(SaleDetail, SalesDetailAdmin)
admin.site.register(ProductAccounts, ProductAccountsAdmin)
admin.site.register(Consoles, ConsolesAdmin)
admin.site.register(GameDetail, GameDetailAdmin)
admin.site.register(Files, FilesAdmin)
admin.site.register(TypeGames, TypeGamesAdmin)
admin.site.register(TypeAccounts, TypeAccountsAdmin)
admin.site.register(VariablesSistema, SystemVariablesAdmin)
admin.site.register(Licenses, LicencesAdmin)
# ------------------------------------------------------------------ #
#  Coupon admin                                                        #
# ------------------------------------------------------------------ #

class CouponRuleInline(admin.TabularInline):
    model = CouponRule
    extra = 1
    fields = ('rule_type', 'operator', 'value')
    show_change_link = True


@admin.action(description='Desactivar cupones seleccionados')
def deactivate_coupons(modeladmin, request, queryset):
    updated = queryset.update(is_valid=False)
    modeladmin.message_user(
        request,
        f'{updated} cupón(es) desactivado(s) correctamente.',
        messages.SUCCESS,
    )


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    inlines            = [CouponRuleInline]
    actions            = [deactivate_coupons]
    autocomplete_fields = ('user', 'game_details')

    list_display = (
        'name_coupon',
        'is_valid_badge',
        'expiration_date',
        'discount_type',
        'percentage_off',
        'fixed_amount',
        'source',
        'points_given',
        'active_rules_count',
        'total_redemptions',
    )
    list_filter   = ('is_valid', 'discount_type', 'source', 'expiration_date', 'user')
    search_fields = ('name_coupon',)
    date_hierarchy = 'expiration_date'
    ordering      = ('-created_at',)
    list_per_page = 25

    readonly_fields = ('created_at', 'modified_at')
    fieldsets = (
        (
            'Información general',
            {
                'fields': (
                    'name_coupon', 'is_valid', 'expiration_date', 'source',
                    'discount_type', 'percentage_off', 'fixed_amount', 'points_given',
                )
            },
        ),
        (
            'Restricciones',
            {
                'fields': ('user', 'game_details'),
                'description': (
                    'Deja en blanco para que el cupón aplique a todos los usuarios / productos.'
                ),
            },
        ),
        (
            'Auditoría',
            {'fields': ('created_at', 'modified_at'), 'classes': ('collapse',)},
        ),
    )

    @admin.display(description='Válido', boolean=False, ordering='is_valid')
    def is_valid_badge(self, obj):
        if obj.is_valid:
            return format_html(
                '<span style="color:#2e7d32;font-weight:bold;">✔ Activo</span>'
            )
        return format_html(
            '<span style="color:#c62828;font-weight:bold;">✘ Inactivo</span>'
        )

    @admin.display(description='Reglas activas')
    def active_rules_count(self, obj):
        return obj.rules.count()

    @admin.display(description='Usos totales')
    def total_redemptions(self, obj):
        return obj.redemptions.count()


# ------------------------------------------------------------------ #
#  Inventario de Productos admin                                       #
# ------------------------------------------------------------------ #

class HasAccountFilter(SimpleListFilter):
    title = 'tiene cuenta'
    parameter_name = 'has_account'

    def lookups(self, request, model_admin):
        return [
            ('1', 'Con cuenta'),
            ('0', 'Sin cuenta'),
        ]

    def queryset(self, request, queryset):
        if self.value() == '1':
            return queryset.filter(cuenta__isnull=False)
        if self.value() == '0':
            return queryset.filter(cuenta__isnull=True)
        return queryset


@admin.action(description='Marcar como vendido (stock = 0)')
def marcar_vendido_inventario(modeladmin, request, queryset):
    updated = queryset.update(stock=0)
    modeladmin.message_user(
        request,
        f'{updated} ítem(s) marcado(s) como vendido — stock puesto en 0.',
        messages.SUCCESS,
    )


@admin.register(GameDetailInventario)
class GameDetailInventarioAdmin(admin.ModelAdmin):

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related('producto', 'consola', 'licencia', 'cuenta')
            .order_by('producto__title', 'licencia', 'consola')
        )

    # ---- column helpers ------------------------------------------------

    @admin.display(description='Producto', ordering='producto__title')
    def col_producto(self, obj):
        if obj.producto:
            url = reverse('admin:products_products_change', args=[obj.producto.id_product])
            return format_html('<a href="{}">{}</a>', url, obj.producto.title)
        return '—'

    @admin.display(description='Licencia', ordering='licencia__descripcion')
    def col_licencia(self, obj):
        return str(obj.licencia) if obj.licencia else '—'

    @admin.display(description='Consola', ordering='consola__descripcion')
    def col_consola(self, obj):
        return obj.consola or '—'

    @admin.display(description='Nombre de cuenta', ordering='cuenta__cuenta')
    def col_account_name(self, obj):
        if obj.cuenta:
            url = reverse('admin:products_productaccounts_change', args=[obj.cuenta.id_product_accounts])
            return format_html('<a href="{}" target="_blank">{}</a>', url, obj.cuenta.cuenta)
        return '—'

    @admin.display(description='Contraseña')
    def col_account_password(self, obj):
        return obj.cuenta.password if obj.cuenta and obj.cuenta.password else '—'

    list_display = (
        'col_producto',
        'col_licencia',
        'col_consola',
        'col_account_name',
        'col_account_password',
        'stock',
    )
    list_editable = ('stock',)
    list_filter = ('licencia', 'consola', HasAccountFilter)
    search_fields = (
        'producto__title',
        'cuenta__cuenta',
    )
    list_per_page = 25
    actions = [marcar_vendido_inventario]

    # ---- change form: only stock is editable, rest are informational ----
    readonly_fields = (
        'col_producto', 'col_licencia', 'col_consola',
        'col_account_name', 'col_account_password',
    )
    fieldsets = (
        ('Información del ítem', {
            'fields': ('col_producto', 'col_licencia', 'col_consola'),
        }),
        ('Cuenta asociada', {
            'fields': ('col_account_name', 'col_account_password'),
        }),
        ('Stock', {
            'fields': ('stock',),
            'description': 'Modifica el stock manualmente. Ponlo en 0 para quitarlo de la venta.',
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return True  # allow editing stock


# ------------------------------------------------------------------ #
#  Productos Destacados admin                                          #
# ------------------------------------------------------------------ #

@admin.action(description='Marcar como Destacado')
def marcar_destacado(modeladmin, request, queryset):
    updated = queryset.update(destacado=True)
    modeladmin.message_user(
        request,
        f'{updated} producto(s) marcado(s) como destacado.',
        messages.SUCCESS,
    )


@admin.action(description='Quitar de Destacados')
def quitar_destacado(modeladmin, request, queryset):
    updated = queryset.update(destacado=False)
    modeladmin.message_user(
        request,
        f'{updated} producto(s) quitado(s) de destacados.',
        messages.SUCCESS,
    )


class DestacadoFilter(SimpleListFilter):
    """Filter to switch quickly between featured / not-featured products."""

    title = 'estado destacado'
    parameter_name = 'destacado'

    def lookups(self, request, model_admin):
        return [
            ('1', 'Solo destacados'),
            ('0', 'No destacados'),
        ]

    def queryset(self, request, queryset):
        if self.value() == '1':
            return queryset.filter(destacado=True)
        if self.value() == '0':
            return queryset.filter(destacado=False)
        return queryset


@admin.register(ProductoDestacado)
class ProductoDestacadoAdmin(admin.ModelAdmin):
    list_display = ('title', 'destacado')
    list_editable = ('destacado',)
    list_filter = (DestacadoFilter, 'tipo_juego', 'consola')
    search_fields = ('title',)
    actions = [marcar_destacado, quitar_destacado]
    list_per_page = 20

    # Only expose the fields that make sense for this view
    fields = ('title', 'destacado')
    readonly_fields = ('title',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CouponRedemption)
class CouponRedemptionAdmin(admin.ModelAdmin):
    list_display   = ('coupon_name', 'username', 'order_id', 'redeemed_at')
    list_filter    = ('coupon', 'user', 'redeemed_at')
    search_fields  = ('coupon__name_coupon', 'user__username', 'order_id')
    ordering       = ('-redeemed_at',)
    date_hierarchy = 'redeemed_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Cupón', ordering='coupon__name_coupon')
    def coupon_name(self, obj):
        return obj.coupon.name_coupon

    @admin.display(description='Usuario', ordering='user__username')
    def username(self, obj):
        return obj.user.username


@admin.register(CouponPurgeLog)
class CouponPurgeLogAdmin(admin.ModelAdmin):
    list_display  = ('source', 'period', 'count')
    list_filter   = ('source', 'period')
    ordering      = ('-period', 'source')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
