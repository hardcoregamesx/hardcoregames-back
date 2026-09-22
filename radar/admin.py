# -*- coding: utf-8 -*-
"""Vista del radar en el admin: revisar oportunidades, aprobarlas y publicarlas.

El flujo es de dos pasos a proposito. "Aprobar" fija el precio sugerido y la
region mas barata pero no toca la tienda, para poder revisar los precios con
calma. "Publicar" ya crea el producto real y lo pone a la venta.
"""
from collections import Counter

from django.contrib import admin, messages
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from radar.models import (
    EjecucionRadar,
    Franquicia,
    MapeoConsola,
    JuegoDetectado,
    ParametrosRadar,
    PrecioRegional,
    TasaCambio,
    TasaTienda,
)


def _pesos(valor):
    if valor is None:
        return '-'
    return '$ {:,.0f}'.format(valor).replace(',', '.')


@admin.register(ParametrosRadar)
class ParametrosRadarAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'factor_precio_venta', 'margen_minimo_cop', 'descuento_minimo_pct',
                    'consola_xbox', 'consola_ps', 'licencia_default',
                    'licencia_primaria', 'licencia_secundaria', 'factor_cuenta',
                    'tipo_producto', 'stock_publicacion', 'actualizado']

    def has_add_permission(self, request):
        # Es una fila unica de configuracion.
        return not ParametrosRadar.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MapeoConsola)
class MapeoConsolaAdmin(admin.ModelAdmin):
    list_display = ['plataforma', 'consola', 'activa']
    list_editable = ['consola', 'activa']

    def has_add_permission(self, request):
        # Las plataformas las define la tienda, no se inventan aqui. Aparecen
        # solas cuando el radar encuentra una nueva.
        return False


@admin.register(Franquicia)
class FranquiciaAdmin(admin.ModelAdmin):
    list_display = ['termino', 'activa', 'nota']
    list_editable = ['activa', 'nota']
    search_fields = ['termino']
    list_filter = ['activa']


class RelevanciaFilter(admin.SimpleListFilter):
    """Separa lo que vale la pena mirar del ruido.

    El radar trae cientos de ofertas por ciclo y la mayoria son juegos que
    nadie pide. Dos senales distintas los separan: las resenas de la propia
    tienda (lo que se vende alla) y la lista de franquicias vigiladas (lo que
    se vende aqui, que es criterio del dueno). Ninguna sirve sola.
    """

    title = 'relevancia'
    parameter_name = 'relevancia'

    RESENAS_CONOCIDO = 20
    RESENAS_POPULAR = 100

    def lookups(self, request, model_admin):
        return [
            ('vale', 'Vale la pena mirarlo'),
            ('franquicia', 'De franquicia vigilada'),
            ('conocidos', 'Con %s+ resenas' % self.RESENAS_CONOCIDO),
            ('populares', 'Con %s+ resenas' % self.RESENAS_POPULAR),
            ('catalogo', 'Ya lo vendes'),
            ('ruido', 'Ruido (sin resenas ni franquicia)'),
        ]

    @staticmethod
    def _q_franquicia():
        terminos = Franquicia.terminos_activos()
        if not terminos:
            return Q(pk__in=[])
        condicion = Q()
        for termino in terminos:
            condicion |= Q(titulo__icontains=termino)
        return condicion

    def queryset(self, request, queryset):
        valor = self.value()
        if not valor:
            return queryset
        franquicia = self._q_franquicia()
        if valor == 'franquicia':
            return queryset.filter(franquicia)
        if valor == 'conocidos':
            return queryset.filter(rating_conteo__gte=self.RESENAS_CONOCIDO)
        if valor == 'populares':
            return queryset.filter(rating_conteo__gte=self.RESENAS_POPULAR)
        if valor == 'catalogo':
            return queryset.exclude(producto_existente_id=None)
        if valor == 'vale':
            return queryset.filter(
                franquicia
                | Q(rating_conteo__gte=self.RESENAS_CONOCIDO)
                | ~Q(producto_existente_id=None)
            )
        if valor == 'ruido':
            return queryset.exclude(franquicia).filter(
                rating_conteo__lt=self.RESENAS_CONOCIDO, producto_existente_id=None)
        return queryset


@admin.register(TasaTienda)
class TasaTiendaAdmin(admin.ModelAdmin):
    list_display = ['tienda', 'factor', 'col_descuento', 'col_pesos', 'muestras', 'manual', 'actualizado']
    list_editable = ['factor', 'manual']
    readonly_fields = ['muestras', 'nota', 'actualizado']

    def has_add_permission(self, request):
        return False

    @admin.display(description='Descuento')
    def col_descuento(self, obj):
        return '%.1f%%' % ((1 - float(obj.factor)) * 100)

    @admin.display(description='Pesos por dolar de saldo')
    def col_pesos(self, obj):
        return _pesos(obj.cop_por_dolar)


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
        'titulo', 'tienda', 'col_estado', 'col_precio_co', 'col_mejor', 'col_costo',
        'col_venta', 'precio_venta', 'precio_cuenta', 'col_margen', 'col_vence', 'col_popularidad',
        'col_catalogo',
    ]
    list_editable = ['precio_venta', 'precio_cuenta']
    list_filter = [RelevanciaFilter, 'estado', 'tienda', 'comprable_co', 'visto_ultimo']
    search_fields = ['titulo', 'id_externo', 'generos']
    readonly_fields = ['visto_primero', 'visto_ultimo', 'publicado_en', 'producto_publicado_id']
    inlines = [PrecioRegionalInline]
    list_per_page = 50
    ordering = ['-rating_conteo', 'titulo']
    actions = ['accion_publicar_todos', 'accion_publicar', 'accion_aprobar',
               'accion_descartar', 'accion_despublicar']

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('precios')

    @admin.display(description='Estado')
    def col_estado(self, obj):
        colores = {
            'nuevo': '#7f8c8d', 'aprobado': '#2980b9', 'publicado': '#27ae60',
            'descartado': '#c0392b', 'vencido': '#d35400',
        }
        return format_html(
            '<b style="color:{}">{}</b>', colores.get(obj.estado, '#000'), obj.get_estado_display())

    @admin.action(description='Publicar SOLO los seleccionados')
    def accion_publicar(self, request, queryset):
        """Publica en un solo paso.

        Antes habia que aprobar y luego publicar. Quien ya escribio los precios
        no tiene por que dar dos pasos, asi que la preparacion va incluida. La
        accion sigue siendo explicita a proposito: escribir un precio suele ser
        para ver como queda el margen, y publicar al guardar dejaria juegos a la
        venta por accidente.
        """
        parametros = ParametrosRadar.actuales()
        publicados, sin_region, fallos = 0, 0, []
        for juego in queryset.prefetch_related('precios'):
            if not juego.preparar(parametros):
                sin_region += 1
                continue
            try:
                juego.publicar(parametros)
                publicados += 1
            except ValueError as exc:
                fallos.append(str(exc))
        if publicados:
            self.message_user(
                request, '%s juegos publicados y ya visibles en la landing.' % publicados,
                messages.SUCCESS)
        if sin_region:
            self.message_user(
                request, '%s sin region donde comprarlos: no se publicaron.' % sin_region,
                messages.WARNING)
        for mensaje in fallos[:5]:
            self.message_user(request, mensaje, messages.ERROR)

    def get_urls(self):
        """Una URL propia para el boton de publicar todos.

        Las acciones del admin exigen una seleccion; poner el precio ya es la
        decision de vender, asi que recorrer la lista otra vez marcando casillas
        era trabajo repetido. Esta vista no necesita seleccion.
        """
        propias = [
            path('publicar-todos/', self.admin_site.admin_view(self.vista_publicar_todos),
                 name='radar_publicar_todos'),
        ]
        return propias + super().get_urls()

    def vista_publicar_todos(self, request):
        self._publicar_con_precio(request)
        return redirect(request.META.get('HTTP_REFERER')
                        or reverse('admin:radar_juegodetectado_changelist'))

    def _publicar_con_precio(self, request):
        """Publica todo lo que tenga precio, mire donde mire la seleccion.

        No toca lo descartado ni lo vencido: eso se saco de circulacion a
        proposito y volver a publicarlo seria justo lo contrario.
        """
        candidatos = (JuegoDetectado.objects
                      .exclude(estado__in=['descartado', 'vencido'])
                      .filter(Q(precio_venta__gt=0) | Q(precio_cuenta__gt=0))
                      .prefetch_related('precios'))

        parametros = ParametrosRadar.actuales()
        total = 0
        publicados, sin_region = 0, 0
        fallos = Counter()
        for juego in candidatos:
            total += 1
            if not juego.preparar(parametros):
                sin_region += 1
                continue
            try:
                juego.publicar(parametros)
                publicados += 1
            except ValueError as exc:
                fallos[str(exc)] += 1

        if publicados:
            self.message_user(
                request,
                '%s juegos con precio publicados y ya visibles en la landing.' % publicados,
                messages.SUCCESS)
        elif total == 0:
            # Solo se dice "ninguno tenia precio" cuando de verdad no habia
            # candidatos. Decirlo cuando fallaron por otra causa manda a buscar
            # el problema donde no esta.
            self.message_user(
                request,
                'Ningun juego tenia precio. Escribe precios en las columnas y vuelve a intentarlo.',
                messages.WARNING)

        if sin_region:
            self.message_user(
                request, '%s sin region donde comprarlos: no se publicaron.' % sin_region,
                messages.WARNING)

        # Un mismo fallo de configuracion afecta a todos los juegos a la vez:
        # repetirlo una vez por juego llena la pantalla y no dice nada nuevo.
        enlace = reverse('admin:radar_parametrosradar_changelist')
        for mensaje, veces in fallos.most_common():
            texto = mensaje if veces == 1 else '%s (afecta a %s juegos)' % (mensaje, veces)
            if 'Parametros del radar' in mensaje:
                self.message_user(
                    request,
                    format_html('{} <a href="{}" style="color:#fff;text-decoration:underline">'
                                'Abrir Parametros del radar</a>', texto, enlace),
                    messages.ERROR)
            else:
                self.message_user(request, texto, messages.ERROR)

    @admin.action(description='PUBLICAR TODOS los que tengan precio (ignora la seleccion)')
    def accion_publicar_todos(self, request, queryset):
        self._publicar_con_precio(request)

    @admin.action(description='Solo preparar (precios y region, sin publicar)')
    def accion_aprobar(self, request, queryset):
        parametros = ParametrosRadar.actuales()
        listos = 0
        for juego in queryset.prefetch_related('precios'):
            if juego.preparar(parametros):
                juego.estado = 'aprobado'
                juego.save(update_fields=['estado'])
                listos += 1
        self.message_user(
            request, '%s preparados. Revisa los precios y luego publica.' % listos,
            messages.SUCCESS)

    @admin.action(description='Descartar')
    def accion_descartar(self, request, queryset):
        n = queryset.update(estado='descartado')
        self.message_user(request, '%s descartados.' % n, messages.SUCCESS)

    @admin.action(description='Retirar de la tienda (deja el producto agotado)')
    def accion_despublicar(self, request, queryset):
        n = 0
        for juego in queryset:
            juego.despublicar()
            n += 1
        self.message_user(request, '%s retirados de la tienda.' % n, messages.SUCCESS)

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
        # Sin decir a que licencia corresponde, este numero induce a publicar
        # una cuenta al precio de un codigo.
        filas = obj.sugeridos_por_licencia()
        if not filas:
            return _pesos(obj.precio_venta_sugerido())
        return format_html('<br>'.join('{}: {}'.format(nombre, _pesos(precio))
                                       for nombre, precio in filas))

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
