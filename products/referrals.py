"""Sistema de referidos: cashback del 1% al dueño de un código de referido.

Cada usuario tiene como máximo un código (tabla ``referral_code``). Cuando una
compra se confirma con ese código, o una reserva de preventa física queda
pagada por completo, el dueño gana el 1% de lo realmente pagado.

El cashback NO entra de inmediato al saldo: nace 'pending' y solo pasa a
'credited' (sumándose a ``users_user_customized.balance_exchange``, el "saldo de
descuento") HOLD_DAYS días después, cuando ya cerró la ventana de reembolso.
``release_due()`` hace ese paso y lo corre un cron (comando
``release_referral_rewards``). Si la venta se cancela antes, el cashback pending
simplemente se anula; si ya estaba acreditado, se descuenta del saldo (sin bajar
de 0).

Cada cashback queda en ``referral_reward`` con unicidad (source_type, source_ref):
reintentos de webhook o de ``confirm_sale`` nunca pagan dos veces. Esquema en
docs/referidos.sql. Todo es "mejor esfuerzo": un fallo aquí se registra pero NUNCA
debe romper una venta ya cobrada.
"""
import logging
import re

from django.db import connection, transaction as db_transaction

logger = logging.getLogger(__name__)

CASHBACK_PERCENT = 1
HOLD_DAYS = 3
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
    """Registra el cashback como 'pending' (disponible en HOLD_DAYS días).

    Devuelve el monto registrado, o 0 si no aplica: sin código válido, monto 0,
    el comprador es el dueño del código, o ese (source_type, source_ref) ya existe.
    """
    code = normalize(code)
    if not code or not CODE_RE.match(code):
        return 0
    cashback = cashback_for(amount_paid)
    if cashback <= 0:
        return 0
    try:
        with db_transaction.atomic(), connection.cursor() as cur:
            cur.execute('SELECT user_id FROM referral_code WHERE code = %s', [code])
            row = cur.fetchone()
            if not row:
                return 0
            referrer_id = row[0]
            if buyer_id is not None and str(buyer_id) == str(referrer_id):
                return 0
            cur.execute(
                'INSERT INTO referral_reward '
                '(referrer_id, referred_user_id, code, source_type, source_ref, base_amount, cashback, '
                " status, available_at) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', "
                "now() + make_interval(days => %s)) "
                'ON CONFLICT (source_type, source_ref) DO NOTHING RETURNING id',
                [referrer_id, buyer_id, code, source_type, str(source_ref), int(amount_paid), cashback, HOLD_DAYS],
            )
            return cashback if cur.fetchone() is not None else 0
    except Exception:
        logger.exception('referidos: no se pudo registrar %s/%s (código %s)', source_type, source_ref, code)
        return 0


def credit_for_transaction(code, buyer_id, transaction):
    """Compra normal: base = lo cobrado en la Transactions (ya con descuentos y saldo aplicado)."""
    if not code or transaction is None:
        return 0
    return credit_referral(code, buyer_id, 'order', transaction.id_transaction, transaction.amount)


def release_due():
    """Pasa a 'credited' (y suma al saldo) lo 'pending' cuya espera ya terminó.
    Idempotente y seguro de correr en paralelo. Devuelve cuántos cashbacks liberó."""
    with db_transaction.atomic(), connection.cursor() as cur:
        cur.execute(
            "WITH due AS ("
            "  UPDATE referral_reward SET status = 'credited', released_at = now() "
            "  WHERE status = 'pending' AND available_at <= now() RETURNING referrer_id, cashback), "
            "sums AS (SELECT referrer_id, SUM(cashback) AS total FROM due GROUP BY referrer_id), "
            "bal AS (UPDATE users_user_customized u SET balance_exchange = u.balance_exchange + sums.total "
            "  FROM sums WHERE u.user_id = sums.referrer_id RETURNING u.user_id) "
            "SELECT (SELECT COUNT(*) FROM due), (SELECT COUNT(*) FROM sums), (SELECT COUNT(*) FROM bal)"
        )
        released, referrers, updated = cur.fetchone()
    if referrers != updated:
        logger.error('referidos: %s referidores sin perfil users_user_customized al liberar cashback',
                     referrers - updated)
    return released


def revert_referral(source_type, source_ref, base_amount=None):
    """Revierte el cashback de una venta cancelada/reembolsada. Devuelve lo revertido (COP).

    - 'pending': solo se anula (no había tocado el saldo).
    - 'credited': se descuenta del saldo, sin bajar de 0.
    - ``base_amount``: si es menor al monto base original (cancelación de UN ítem de una
      compra con varios), revierte solo ese pedazo y el resto sigue vigente.
    """
    try:
        with db_transaction.atomic(), connection.cursor() as cur:
            cur.execute(
                'SELECT id, referrer_id, base_amount, cashback, status FROM referral_reward '
                "WHERE source_type = %s AND source_ref = %s AND status IN ('pending', 'credited') FOR UPDATE",
                [source_type, str(source_ref)],
            )
            row = cur.fetchone()
            if not row:
                return 0
            rid, referrer_id, base, cashback, status = row
            partial = base_amount is not None and 0 < int(base_amount) < base
            quitar = min(cashback_for(base_amount), cashback) if partial else cashback
            if quitar <= 0:
                return 0
            if partial:
                cur.execute(
                    'UPDATE referral_reward SET base_amount = base_amount - %s, cashback = cashback - %s WHERE id = %s',
                    [int(base_amount), quitar, rid],
                )
            else:
                cur.execute(
                    "UPDATE referral_reward SET status = 'reverted', reverted_at = now() WHERE id = %s", [rid]
                )
            if status == 'credited':
                cur.execute(
                    'UPDATE users_user_customized SET balance_exchange = GREATEST(balance_exchange - %s, 0) '
                    'WHERE user_id = %s',
                    [quitar, referrer_id],
                )
            return quitar
    except Exception:
        logger.exception('referidos: no se pudo revertir %s/%s', source_type, source_ref)
        return 0
