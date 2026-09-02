from datetime import datetime, timezone

from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.utils.html import format_html, format_html_join

from .models import Sorteo, SorteoWinner
from .services import STATUS_PARTICIPA, draw_winners, participation_rows


class SorteoWinnerInline(admin.TabularInline):
    model = SorteoWinner
    extra = 0
    fields = ('user', 'drawn_at')
    readonly_fields = ('user', 'drawn_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        # Los ganadores solo se crean via la accion "Ejecutar sorteo" (o el
        # comando ejecutar_sorteos_vencidos que corre por cron).
        return False


@admin.action(description='Ejecutar sorteo (elige ganadores al azar)')
def ejecutar_sorteo(modeladmin, request, queryset):
    for sorteo in queryset:
        if sorteo.status == 'FINISHED':
            modeladmin.message_user(
                request, f'"{sorteo}" ya fue ejecutado, se omite.', level=messages.WARNING,
            )
            continue

        chosen, calificados = draw_winners(sorteo)

        if not chosen:
            modeladmin.message_user(
                request, f'"{sorteo}": nadie califica todavía, no se eligió ningún ganador.',
                level=messages.WARNING,
            )
            continue

        modeladmin.message_user(
            request, f'"{sorteo}": {len(chosen)} ganador(es) elegido(s) entre {calificados} calificados.',
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
        return len(participation_rows(obj))
    participantes_count.short_description = 'Participan (≠ No participa)'

    def participantes_actuales(self, obj):
        if obj is None or obj.pk is None:
            return 'Disponible después de guardar el sorteo.'
        if obj.status != 'ACTIVE':
            return 'Solo se calcula para sorteos activos.'

        rows = participation_rows(obj)
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
