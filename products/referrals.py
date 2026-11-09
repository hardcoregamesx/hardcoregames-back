"""Sistema de referidos: cashback del 1% al dueño de un código de referido.

Cada usuario tiene como máximo un código (tabla ``referral_code``). Cuando una
compra (o un pago de preventa física) se confirma con ese código, el dueño gana
el 1% de lo realmente pagado, acreditado a ``users_user_customized.balance_exchange``
("saldo de descuento"). Cada acreditación queda en ``referral_reward`` con
unicidad (source_type, source_ref), de modo que reintentos de webhook o de
``confirm_sale`` nunca pagan dos veces.

Las tablas se crean con SQL directo (la app no usa migraciones), ver
docs/referidos.sql. Todo lo de este módulo es "mejor esfuerzo": un fallo aquí
se registra pero NUNCA debe romper una venta ya cobrada.
"""
import logging
import re

from django.db import connection, transaction as db_transaction

logger = logging.getLogger(__name__)

CASHBACK_PERCENT = 1
CODE_RE = re.compile(r'^[a-z0-9]{4,20}$')


def normalize(code):
    return str(code or '').strip().lower()


def cashback_for(amount_paid):
    """1% entero hacia abajo (COP no tiene centavos útiles)."""
    try:
        amount = int(amount_paid)
    except (TypeError, ValueError):
        return 0
    return amount * CASHBACK_PERCENT // 100 if amount > 0 else 0


def code_exists(code):
    code = normalize(code)
    if not CODE_RE.match(code):
        return False
    with connection.cursor() as cur:
        cur.execute('SELECT 1 FROM referral_code WHERE code = %s', [code])
        return cur.fetchone() is not None


def credit_referral(code, buyer_id, source_type, source_ref, amount_paid):
    """Acredita el cashback. Devuelve el monto acreditado, o 0 si no aplica.

    No aplica si: no hay código o no existe, el monto da 0, el comprador es el
    mismo dueño del código, o ese (source_type, source_ref) ya se acreditó.
    """
    code = normalize(code)
    if not code or not CODE_RE.match(code):
        return 0
    cashback = cashback_for(amount_paid)
    if cashback <= 0:
        return 0
    try:
        with db_transaction.atomic():
            with connection.cursor() as cur:
                cur.execute('SELECT user_id FROM referral_code WHERE code = %s', [code])
                row = cur.fetchone()
                if not row:
                    return 0
                referrer_id = row[0]
                if buyer_id is not None and str(buyer_id) == str(referrer_id):
                    return 0
                cur.execute(
                    'INSERT INTO referral_reward '
                    '(referrer_id, referred_user_id, code, source_type, source_ref, base_amount, cashback) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s) '
                    'ON CONFLICT (source_type, source_ref) DO NOTHING RETURNING id',
                    [referrer_id, buyer_id, code, source_type, str(source_ref), int(amount_paid), cashback],
                )
                if cur.fetchone() is None:
                    return 0  # ya acreditado antes (reintento)
                cur.execute(
                    'UPDATE users_user_customized SET balance_exchange = balance_exchange + %s WHERE user_id = %s',
                    [cashback, referrer_id],
                )
                if cur.rowcount == 0:
                    # Sin perfil no hay donde acreditar: deshacer el registro para no dejar un
                    # cashback "pagado" que nunca llegó.
                    raise RuntimeError(f'referidos: el usuario {referrer_id} no tiene users_user_customized')
        return cashback
    except Exception:
        logger.exception('referidos: no se pudo acreditar %s/%s (código %s)', source_type, source_ref, code)
        return 0


def credit_for_transaction(code, buyer_id, transaction):
    """Compra normal: base = lo cobrado en la Transactions (ya con descuentos y saldo aplicado)."""
    if not code or transaction is None:
        return 0
    return credit_referral(code, buyer_id, 'order', transaction.id_transaction, transaction.amount)


def revert_referral(source_type, source_ref):
    """Revierte un cashback acreditado (reembolso). El saldo nunca baja de 0."""
    try:
        with db_transaction.atomic():
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE referral_reward SET status = 'reverted', reverted_at = now() "
                    "WHERE source_type = %s AND source_ref = %s AND status = 'credited' "
                    'RETURNING referrer_id, cashback',
                    [source_type, str(source_ref)],
                )
                row = cur.fetchone()
                if not row:
                    return 0
                cur.execute(
                    'UPDATE users_user_customized SET balance_exchange = GREATEST(balance_exchange - %s, 0) '
                    'WHERE user_id = %s',
                    [row[1], row[0]],
                )
                return row[1]
    except Exception:
        logger.exception('referidos: no se pudo revertir %s/%s', source_type, source_ref)
        return 0
