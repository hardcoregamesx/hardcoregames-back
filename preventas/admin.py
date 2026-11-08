import csv

from django.contrib import admin, messages
from django.http import HttpResponse
from django.utils import timezone

from . import services
from .models import (
    ESTADO_CANCELADA, ESTADO_DESPACHADA, ESTADO_REEMBOLSADA, CiudadIntermedia, Pago, Preventa, Reserva,
)


class PagoInline(admin.TabularInline):
    model = Pago
    extra = 0
    can_delete = False
    fields = ('transaction_id', 'tipo', 'monto', 'status', 'nombre_pagador', 'created_at')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Preventa)
class PreventaAdmin(admin.ModelAdmin):
    list_display = ('title', 'active', 'fase', 'reserva_unit', 'rango_preventa', 'rango_tardia',
                    'tardia_disponibles', 'entrega_desde', 'entrega_hasta', 'reservas_count')
    list_filter = ('active',)
    search_fields = ('title', 'slug')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('fase_actual_txt', 'created_at')
    fieldsets = (
        ('General', {'fields': ('title', 'slug', 'description', 'image_url', 'active', 'fase_actual_txt')}),
        ('Reserva y pagos', {'fields': ('reserva_unit', 'breb_key', 'envio_nacional_est')}),
        ('Abonos libres', {'fields': ('permitir_abonos', 'abono_minimo')}),
        ('Fechas de entrega (juegos físicos)', {'fields': ('entrega_desde', 'entrega_hasta')}),
        ('Enlace externo (Zelda / GTA VI)', {'fields': ('enlace_externo',), 'classes': ('collapse',)}),
        ('Fase 1 — Preventa', {'fields': ('pre_min', 'pre_max', 'pre_final')}),
        ('Cambio automático', {'fields': ('switch_at',)}),
        ('Fase 2 — Preventa tardía', {'fields': ('tardia_min', 'tardia_max', 'tardia_final', 'tardia_disponibles')}),
    )

    def fase_actual_txt(self, obj):
        if not obj.pk:
            return '—'
        return 'Preventa tardía' if services.fase_actual(obj) == 'TARDIA' else 'Preventa'
    fase_actual_txt.short_description = 'Fase actual'

    def fase(self, obj):
        return self.fase_actual_txt(obj)

    def rango_preventa(self, obj):
        return f'${obj.pre_min:,} – ${obj.pre_max:,}' + (f' (final ${obj.pre_final:,})' if obj.pre_final else '')
    rango_preventa.short_description = 'Preventa'

    def rango_tardia(self, obj):
        return f'${obj.tardia_min:,} – ${obj.tardia_max:,}' + (f' (final ${obj.tardia_final:,})' if obj.tardia_final else '')
    rango_tardia.short_description = 'Tardía'

    def reservas_count(self, obj):
        return obj.reservas.exclude(estado__in=('EXPIRADA', 'CANCELADA', 'REEMBOLSADA')).count()
    reservas_count.short_description = 'Reservas vivas'


@admin.register(CiudadIntermedia)
class CiudadIntermediaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activa', 'costo_estimado', 'orden')
    list_editable = ('activa', 'costo_estimado', 'orden')


@admin.action(description='Exportar CSV (para armar despachos)')
def exportar_csv(modeladmin, request, queryset):
    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="reservas_preventas.csv"'
    resp.write('﻿')
    w = csv.writer(resp)
    w.writerow(['Código', 'Preventa', 'Fase', 'Unidades', 'Estado', 'Nombre', 'WhatsApp', 'Cédula', 'Dirección',
                'Ciudad', 'Envío', 'Ciudad intermedia', 'Total abonado', 'Saldo estimado/pendiente',
                'Guía / domiciliario', 'Fecha despacho', 'Cómo nos conoció', 'Fecha reserva'])
    for r in queryset.select_related('preventa'):
        s = services.saldo_info(r)
        saldo = s['saldo'] if s['definitivo'] else f"{s['saldo_min']}–{s['saldo_max']}"
        w.writerow([r.codigo, r.preventa.title, r.fase, r.unidades, r.estado, r.nombre, r.whatsapp, r.cedula,
                    r.direccion, r.ciudad, r.envio_tipo, r.ciudad_intermedia, s['abonado'],
                    saldo, r.guia, r.despachado_at.strftime('%Y-%m-%d %H:%M') if r.despachado_at else '',
                    r.fuente, r.created_at.strftime('%Y-%m-%d %H:%M')])
    return resp


@admin.action(description='Cancelar y devolver cupo')
def cancelar(modeladmin, request, queryset):
    for r in queryset:
        services.cerrar_reserva(r.pk, ESTADO_CANCELADA)
    modeladmin.message_user(request, f'{queryset.count()} reserva(s) canceladas.', level=messages.SUCCESS)


@admin.action(description='Marcar como reembolsada y devolver cupo')
def reembolsada(modeladmin, request, queryset):
    for r in queryset:
        services.cerrar_reserva(r.pk, ESTADO_REEMBOLSADA)
    modeladmin.message_user(request, f'{queryset.count()} reserva(s) marcadas como reembolsadas.', level=messages.SUCCESS)


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'preventa', 'fase', 'unidades', 'nombre', 'whatsapp', 'ciudad', 'estado',
                    'guia', 'despachado_at', 'created_at')
    list_filter = ('preventa', 'estado', 'fase', 'envio_tipo', 'fuente')
    search_fields = ('codigo', 'nombre', 'whatsapp', 'cedula', 'ciudad', 'guia')
    date_hierarchy = 'created_at'
    actions = [exportar_csv, cancelar, reembolsada]
    inlines = [PagoInline]
    readonly_fields = ('codigo', 'preventa', 'fase', 'unidades', 'nombre', 'whatsapp', 'direccion', 'ciudad',
                       'cedula', 'fuente', 'envio_tipo', 'ciudad_intermedia', 'reserva_total', 'saldo_txt',
                       'despachado_at', 'expires_at', 'paid_at', 'saldo_paid_at', 'created_at')
    fieldsets = (
        ('Reserva', {'fields': ('codigo', 'preventa', 'fase', 'unidades', 'estado', 'reserva_total', 'saldo_txt',
                                'paid_at', 'saldo_paid_at', 'created_at')}),
        ('Cliente', {'fields': ('nombre', 'whatsapp', 'cedula', 'fuente')}),
        ('Envío', {'fields': ('direccion', 'ciudad', 'envio_tipo', 'ciudad_intermedia')}),
        ('Despacho', {'fields': ('guia', 'despachado_at', 'notas'),
                      'description': 'Al llenar la guía, la fecha de despacho se guarda sola y el estado pasa a Despachada.'}),
    )

    def has_add_permission(self, request):
        return False

    def saldo_txt(self, obj):
        s = services.saldo_info(obj)
        if s['definitivo']:
            return f"${s['saldo']:,} (precio final ${s['precio_unit']:,} c/u) · abonado ${s['abonado']:,}"
        return f"${s['saldo_min']:,} – ${s['saldo_max']:,} (estimado, sin precio final) · abonado ${s['abonado']:,}"
    saldo_txt.short_description = 'Saldo pendiente'

    def save_model(self, request, obj, form, change):
        if obj.guia.strip() and not obj.despachado_at:
            obj.despachado_at = timezone.now()
            if obj.estado in ('RESERVADA', 'PAGADA'):
                obj.estado = ESTADO_DESPACHADA
        super().save_model(request, obj, form, change)
