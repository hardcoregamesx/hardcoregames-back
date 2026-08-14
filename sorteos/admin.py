import random
from datetime import datetime, timezone

from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.db.models import Case, Count, F, IntegerField, Sum, When
from django.utils.html import format_html, format_html_join

from products.models import SaleDetail
from .models import Sorteo, SorteoWinner


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


STATUS_PARTICIPA = 'Participa'
STATUS_PARCIAL = 'Parcial'


# Precio efectivo de una venta: precio_descuento cuando esta configurado
# (>0), si no el precio de lista. Mismo criterio que
# SerializerForGameDetailByProduct.get_price en products/productSerializers.py.
_EFFECTIVE_PRICE = Case(
    When(combinacion__precio_descuento__gt=0, then=F('combinacion__precio_descuento')),
    default=F('combinacion__precio'),
    output_field=IntegerField(),
)


def _participation_rows(sorteo):
    """Filas de products_saledetail (la compra real del storefront, creada
    por confirm_sale en products/views.py) agrupadas por usuario con al
    menos una venta dentro de la ventana del sorteo, con su estado de
    participacion: "Participa" si ya cumple los requisitos (mismo calculo que
    usa hc-fastapi en app/services/sorteos.py para el banner del frontend),
    "Parcial" si tiene compras en el sorteo pero todavia no los cumple. Los
    usuarios sin ninguna compra en la ventana ("No participa") ni siquiera
    aparecen aqui, asi que no hace falta excluirlos aparte: cualquier fila
    que devuelve esta funcion ya es "distinta de No participa".

    OJO: no se calcula contra orders_buy/SorteoOrderBuy (tabla de
    hc-fastapi) -- esa tabla esta practicamente vacia en produccion y su
    campo amount nunca se llena. Ver la nota en sorteos/models.py."""
    rows = (
        SaleDetail.objects
        .filter(
            usuario_id__isnull=False,
            combinacion_id__isnull=False,
            fecha_venta__gte=sorteo.start_date,
            fecha_venta__lte=sorteo.end_date,
        )
        .values('usuario_id')
        .annotate(purchases_count=Count('id_sale_detail'), amount_sum=Sum(_EFFECTIVE_PRICE))
    )
    result = []
    for row in rows:
        qualifies = _qualifies(row['purchases_count'], row['amount_sum'], sorteo)
        result.append({
            'user_id': row['usuario_id'],
            'purchases_count': row['purchases_count'],
            'amount_sum': row['amount_sum'],
            'status': STATUS_PARTICIPA if qualifies else STATUS_PARCIAL,
        })
    return result


@admin.action(description='Ejecutar sorteo (elige ganadores al azar)')
def ejecutar_sorteo(modeladmin, request, queryset):
    for sorteo in queryset:
        if sorteo.status == 'FINISHED':
            modeladmin.message_user(
                request, f'"{sorteo}" ya fue ejecutado, se omite.', level=messages.WARNING,
            )
            continue

        qualified_user_ids = [
            row['user_id'] for row in _participation_rows(sorteo) if row['status'] == STATUS_PARTICIPA
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
    list_display = (
        'title', 'status', 'start_date', 'end_date',
        'min_purchases', 'min_amount', 'require_both', 'winners_count', 'participantes_count',
    )
    list_filter = ('status',)
    search_fields = ('title', 'legend')
    date_hierarchy = 'start_date'
    inlines = [SorteoWinnerInline]
    actions = [ejecutar_sorteo]
    readonly_fields = ('participantes_actuales',)
    fields = (
        'title', 'legend', 'prize_image_url', 'start_date', 'end_date',
        'min_purchases', 'min_amount', 'require_both', 'winners_count', 'status',
        'participantes_actuales',
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_at = datetime.now(timezone.utc)
        super().save_model(request, obj, form, change)

    def participantes_count(self, obj):
        if obj.status != 'ACTIVE':
            return '—'
        return len(_participation_rows(obj))
    participantes_count.short_description = 'Participan (≠ No participa)'

    def participantes_actuales(self, obj):
        if obj is None or obj.pk is None:
            return 'Disponible después de guardar el sorteo.'
        if obj.status != 'ACTIVE':
            return 'Solo se calcula para sorteos activos.'

        rows = _participation_rows(obj)
        if not rows:
            return 'Nadie tiene estado "Participa" ni "Parcial" todavía.'

        usuarios = User.objects.in_bulk([row['user_id'] for row in rows])
        # "Participa" primero, y dentro de cada estado por monto acumulado desc.
        rows.sort(key=lambda r: (r['status'] != STATUS_PARTICIPA, -(r['amount_sum'] or 0)))

        filas_html = format_html_join(
            '',
            '<tr><td>{}</td><td>{}</td><td>{}</td><td>${}</td><td>{}</td></tr>',
            (
                (
                    usuarios[row['user_id']].username if row['user_id'] in usuarios else f'user_id={row["user_id"]}',
                    usuarios[row['user_id']].email if row['user_id'] in usuarios else '',
                    row['purchases_count'],
                    f'{row["amount_sum"] or 0:,.0f}'.replace(',', '.'),
                    row['status'],
                )
                for row in rows
            ),
        )
        participan = sum(1 for row in rows if row['status'] == STATUS_PARTICIPA)
        parciales = len(rows) - participan
        return format_html(
            '<table><thead><tr>'
            '<th>Usuario</th><th>Email</th><th>Compras</th><th>Monto acumulado</th><th>Estado</th>'
            '</tr></thead><tbody>{}</tbody></table>'
            '<p>{} en "Participa", {} en "Parcial" (se excluyen solo los que están en "No participa", '
            'es decir sin ninguna compra en la ventana del sorteo).</p>',
            filas_html, participan, parciales,
        )
    participantes_actuales.short_description = 'Participantes actuales'


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
