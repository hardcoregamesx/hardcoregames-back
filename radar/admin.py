# -*- coding: utf-8 -*-
"""Vista del radar en el admin.

En esta fase el radar solo recoge datos: aqui se miran, no se publican.
"""
from django.contrib import admin
from django.utils.html import format_html

from radar.models import (
    EjecucionRadar,
    JuegoDetectado,
    ParametrosRadar,
    PrecioRegional,
    TasaCambio,
)


def _pesos(valor):
    if valor is None:
        return '-'
    return '$ {:,.0f}'.format(valor).replace(',', '.')


@admin.register(ParametrosRadar)
class ParametrosRadarAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'factor_precio_venta', 'margen_minimo_cop', 'descuento_minimo_pct', 'actualizado']

    def has_add_permission(self, request):
        # Es una fila unica de configuracion.
        return not ParametrosRadar.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TasaCambio)
class TasaCambioAdmin(admin.ModelAdmin):
    list_display = ['moneda', 'cop_por_unidad', 'manual', 'nota', 'actualizado']
    list_filter = ['manual']
    list_editable = ['cop_por_unidad', 'manual']


class PrecioRegionalInline(admin.TabularInline):
    model = PrecioRegional
    extra = 0
    readonly_fields = ['region', 'moneda', 'precio_lista', 'precio_oferta', 'descuento_pct',
                       'comprable', 'costo_cop', 'fecha_fin', 'actualizado']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(JuegoDetectado)
class JuegoDetectadoAdmin(admin.ModelAdmin):
    list_display = [
        'titulo', 'tienda', 'col_precio_co', 'col_mejor', 'col_costo',
        'col_venta', 'col_margen', 'col_vence', 'col_popularidad', 'col_catalogo',
    ]
    list_filter = ['tienda', 'comprable_co', 'visto_ultimo']
    search_fields = ['titulo', 'id_externo', 'generos']
    readonly_fields = ['visto_primero', 'visto_ultimo']
    inlines = [PrecioRegionalInline]
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('precios')

    @admin.display(description='Precio Colombia')
    def col_precio_co(self, obj):
        return _pesos(obj.precio_co_vigente)

    @admin.display(description='Mejor region')
    def col_mejor(self, obj):
        mejor = obj.mejor_precio()
        if not mejor:
            return format_html('<span style="color:#c0392b">sin region comprable</span>')
        return '%s (-%s%%)' % (mejor.region, int(mejor.descuento_pct))

    @admin.display(description='Costo')
    def col_costo(self, obj):
        mejor = obj.mejor_precio()
        return _pesos(mejor.costo_cop) if mejor else '-'

    @admin.display(description='Venta sugerida')
    def col_venta(self, obj):
        return _pesos(obj.precio_venta_sugerido())

    @admin.display(description='Margen')
    def col_margen(self, obj):
        mejor = obj.mejor_precio()
        venta = obj.precio_venta_sugerido()
        if not mejor or venta is None:
            return '-'
        margen = mejor.margen(venta)
        color = '#27ae60' if margen and margen >= 20000 else '#c0392b'
        return format_html('<b style="color:{}">{}</b>', color, _pesos(margen))

    @admin.display(description='Vence')
    def col_vence(self, obj):
        mejor = obj.mejor_precio()
        if not mejor or not mejor.fecha_fin:
            return '-'
        return mejor.fecha_fin.strftime('%d/%m/%Y')

    @admin.display(description='Resenas')
    def col_popularidad(self, obj):
        if not obj.rating_conteo:
            return format_html('<span style="color:#999">sin datos</span>')
        return '%.1f* (%s)' % (obj.rating, obj.rating_conteo)

    @admin.display(description='Ya en catalogo')
    def col_catalogo(self, obj):
        if obj.producto_existente_id:
            return format_html(
                '<span style="color:#e67e22">si, #{}</span>', obj.producto_existente_id)
        return '-'


@admin.register(EjecucionRadar)
class EjecucionRadarAdmin(admin.ModelAdmin):
    list_display = ['tienda', 'inicio', 'fin', 'col_estado', 'regiones', 'juegos_vistos', 'precios_guardados']
    list_filter = ['tienda', 'ok']
    readonly_fields = ['tienda', 'regiones', 'inicio', 'fin', 'ok', 'juegos_vistos',
                       'precios_guardados', 'error']

    def has_add_permission(self, request):
        return False

    @admin.display(description='Estado')
    def col_estado(self, obj):
        if obj.ok:
            return format_html('<b style="color:#27ae60">OK</b>')
        return format_html('<b style="color:#c0392b">FALLO</b>')
