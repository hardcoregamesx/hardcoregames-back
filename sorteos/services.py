"""Logica compartida para elegir ganadores de un sorteo.

Extraida de sorteos/admin.py (accion "Ejecutar sorteo") para que la misma
regla de calificacion y de eleccion la use tambien el comando
ejecutar_sorteos_vencidos, que un cron corre cada 15 minutos para cerrar
solo los sorteos cuya end_date ya paso -- sin esto, elegir ganador era una
accion manual del admin y un sorteo vencido se quedaba en ACTIVE para
siempre si nadie entraba a darle clic (ver memoria
sorteos-diseno-regla-y-datos).
"""

import logging
import random
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Count, Sum

from products.models import Transactions
from utils.SendEmail import SendEmail
from .models import Sorteo, SorteoWinner

logger = logging.getLogger(__name__)

# Estados de pago exitoso vistos en produccion entre los dos gateways que ha
# usado la tienda (Bold via webhook/redirect, y el ePayco legacy que todavia
# deja filas). Verificado con
# SELECT status, COUNT(*) FROM products_transactions GROUP BY status.
TRANSACTION_SUCCESS_STATUSES = ('approved', 'SALE_APPROVED', 'aceptada', 'accepted')

STATUS_PARTICIPA = 'Participa'
STATUS_PARCIAL = 'Parcial'


def qualifies(purchases_count, amount_sum, sorteo):
    has_count_req = sorteo.min_purchases is not None
    has_amount_req = sorteo.min_amount is not None
    count_ok = (not has_count_req) or purchases_count >= sorteo.min_purchases
    amount_ok = (not has_amount_req) or (amount_sum or 0) >= sorteo.min_amount

    if has_count_req and has_amount_req:
        return (count_ok and amount_ok) if sorteo.require_both else (count_ok or amount_ok)
    return count_ok and amount_ok


def participation_rows(sorteo):
    """Filas de products_transactions (el dinero real cobrado, via Bold o el
    ePayco legacy) agrupadas por usuario con al menos un pago exitoso dentro
    de la ventana del sorteo, con su estado de participacion: "Participa" si
    ya cumple los requisitos (mismo calculo que usa hc-fastapi en
    app/services/sorteos.py para el banner del frontend), "Parcial" si tiene
    compras en el sorteo pero todavia no los cumple.

    Una compra = una transaccion (un checkout), no una linea de producto:
    si el carrito tenia 2 productos, cuenta como 1 compra. El monto es lo
    que realmente se cobro (neto de saldo/cupon aplicado), no el precio de
    catalogo -- por eso NO se calcula contra products_saledetail (que no
    guarda monto) ni contra orders_buy/SorteoOrderBuy (tabla de hc-fastapi,
    practicamente vacia en produccion). Ver la nota en sorteos/models.py.
    """
    rows = (
        Transactions.objects
        .filter(
            status__in=TRANSACTION_SUCCESS_STATUSES,
            date_transaction__gte=sorteo.start_date,
            date_transaction__lte=sorteo.end_date,
        )
        .values('user_id')
        .annotate(purchases_count=Count('id_transaction'), amount_sum=Sum('amount'))
    )
    result = []
    for row in rows:
        row_qualifies = qualifies(row['purchases_count'], row['amount_sum'], sorteo)
        result.append({
            'user_id': row['user_id'],
            'purchases_count': row['purchases_count'],
            'amount_sum': row['amount_sum'],
            'status': STATUS_PARTICIPA if row_qualifies else STATUS_PARCIAL,
        })
    return result


def _send_winner_email(sorteo, user):
    """Avisa al ganador reusando la misma plantilla de marca de las
    confirmaciones de compra (settings.EMAIL_FOR_SALE, ver
    products.views.send_email_notification) -- mismo logo, mismos canales de
    soporte, para que no se vea como un correo aparte del resto de la tienda.
    Antes de este cambio nadie avisaba al ganador de nada; se enteraba solo
    si entraba por su cuenta a /rewards/ a revisar."""
    if not user.email:
        logger.warning('Sorteo "%s": ganador user_id=%s sin email, no se pudo avisar.', sorteo, user.id)
        return

    prize_img_html = (
        f'<p style="text-align:center;margin:20px 0;">'
        f'<img src="{sorteo.prize_image_url}" alt="{sorteo.title}" '
        f'style="max-width:260px;border-radius:8px;"></p>'
        if sorteo.prize_image_url else ''
    )
    message_html = (
        f'<h2 style="margin:0 0 12px;color:#ffffff;font-family:Arial,Helvetica,sans-serif;">'
        f'🎉 ¡Ganaste el sorteo "{sorteo.title}"!</h2>'
        f'<p style="margin:0 0 8px;color:#8a9bb8;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:14px;line-height:1.6;">{sorteo.legend}</p>'
        f'{prize_img_html}'
        f'<p style="margin:16px 0 0;color:#8a9bb8;font-family:Arial,Helvetica,sans-serif;font-size:14px;">'
        f'Escríbenos por WhatsApp para coordinar la entrega de tu premio.</p>'
    )

    soup = BeautifulSoup(settings.EMAIL_FOR_SALE, features='html.parser')
    body = soup.find(id='body') or soup
    body.clear()
    body.append(BeautifulSoup(message_html, 'html.parser'))

    SendEmail().__int__(str(soup), f'🎉 ¡Ganaste el sorteo {sorteo.title}!', user.email)


def draw_winners(sorteo):
    """Elige los ganadores de un sorteo ACTIVE y lo marca FINISHED.

    Devuelve None si el sorteo ya estaba FINISHED (nada que hacer). En caso
    contrario devuelve (chosen_user_ids, calificados_totales) -- chosen_user_ids
    puede ser una lista vacia si nadie califica todavia, en cuyo caso el
    sorteo NO se marca FINISHED (se deja ACTIVE para que un cron posterior
    lo reintente, por si una transaccion tarda en conciliarse).
    """
    if sorteo.status == 'FINISHED':
        return None

    qualified_user_ids = [
        row['user_id'] for row in participation_rows(sorteo) if row['status'] == STATUS_PARTICIPA
    ]

    if not qualified_user_ids:
        return [], 0

    winners_count = min(sorteo.winners_count, len(qualified_user_ids))
    chosen = random.sample(qualified_user_ids, winners_count)

    now = datetime.now(timezone.utc)
    SorteoWinner.objects.bulk_create([
        SorteoWinner(sorteo=sorteo, user_id=user_id, drawn_at=now)
        for user_id in chosen
    ])

    sorteo.status = 'FINISHED'
    sorteo.save(update_fields=['status'])

    for user in User.objects.filter(id__in=chosen):
        _send_winner_email(sorteo, user)

    return chosen, len(qualified_user_ids)


def sorteos_vencidos_sin_cerrar():
    """ACTIVE cuya end_date ya paso -- los candidatos que el cron debe cerrar."""
    return Sorteo.objects.filter(status='ACTIVE', end_date__lte=datetime.now(timezone.utc))
