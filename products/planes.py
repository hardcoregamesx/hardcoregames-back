"""Lógica de dominio de "Cuotas y Reserva" (ver docs/cuotas-y-reserva.md).

Todo lo que no es "recibir un request HTTP" para este módulo vive aquí:
armado de planes y cuotas al confirmar una venta, confirmación de pagos de
cuotas siguientes, y el aviso al programa de ventas (hardcoregames-ventas,
§7 de la spec). `products/views.py` y `products/views_planes.py` solo hacen
el trabajo mínimo de request/response y delegan aquí.

Nunca se confía en nada que declare el cliente: los montos de cada plan se
calculan siempre desde el catálogo (GameDetail), igual que
`_calculate_cart_amount` en views.py.
"""
import json
import logging
import os
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone

from products.models import PaymentInstallment, PaymentPlan
from products import emails_planes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Aviso al programa de ventas (hardcoregames-ventas) -- ver spec §7.
# Mismo patrón "best effort" que _notify_ventas_module en views.py: nunca debe
# poder tumbar la confirmación real del pago si falla, solo se loguea.
# ---------------------------------------------------------------------------

VENTAS_PLANES_WEBHOOK_URL = os.getenv(
    "VENTAS_PLANES_WEBHOOK_URL", "https://ventas.srv936408.hstgr.cloud/webhooks/planes/"
)
VENTAS_PLANES_WEBHOOK_SECRET = os.getenv("VENTAS_PLANES_WEBHOOK_SECRET", "")

TRANSFERENCIA_PAYMENT_ID = "transferencia_brebb"


def _titulo_snapshot(gd):
    """"Título | Licencia | Consola" -- formato exacto pedido en la spec
    (distinto del __str__ de GameDetail, que además incluye los días de
    alquiler, que no aplica a cuotas/reserva)."""
    titulo = gd.producto.title if gd.producto else "Producto"
    return f"{titulo} | {gd.licencia} | {gd.consola}"


def crear_plan_cuotas(gd, user, descuento_item, transaction, sale_detail):
    """Crea el PaymentPlan + PaymentInstallment de un ítem 'cuotas' del
    carrito, ya con la primera cuota marcada como pagada (se pagó en el
    mismo checkout). Ver docs/cuotas-y-reserva.md §3.2."""
    inicial = gd.cuota_inicial if gd.cuota_inicial else gd.valor_cuota
    precio_total = inicial + gd.valor_cuota * (gd.num_cuotas - 1)
    ahora = timezone.now()
    monto_inicial = max(inicial - int(descuento_item or 0), 0)

    plan = PaymentPlan.objects.create(
        user=user,
        gamedetail=gd,
        tipo=PaymentPlan.TIPO_CUOTAS,
        estado=PaymentPlan.ESTADO_ACTIVO,
        titulo_snapshot=_titulo_snapshot(gd),
        precio_total=precio_total,
        descuento=int(descuento_item or 0),
        num_cuotas=gd.num_cuotas,
        valor_cuota=gd.valor_cuota,
        cuota_inicial=gd.cuota_inicial,
        total_pagado=monto_inicial,
        transaction_origen=transaction,
        saledetail=sale_detail,
        fecha_creacion=ahora,
        fecha_actualizacion=ahora,
    )
    PaymentInstallment.objects.create(
        plan=plan, numero=1, monto=monto_inicial, mora=0,
        fecha_vencimiento=ahora.date(), estado=PaymentInstallment.ESTADO_PAGADA,
        fecha_pago=ahora, transaction=transaction, metodo="checkout",
    )
    for k in range(2, gd.num_cuotas + 1):
        PaymentInstallment.objects.create(
            plan=plan, numero=k, monto=gd.valor_cuota, mora=0,
            fecha_vencimiento=(ahora + timedelta(days=30 * (k - 1))).date(),
            estado=PaymentInstallment.ESTADO_PENDIENTE,
        )
    return plan


def crear_plan_reserva(gd, user, descuento_item, transaction):
    """Crea el PaymentPlan + PaymentInstallment de un ítem 'reserva' del
    carrito. No toca stock ni crea SaleDetail -- no se entrega nada todavía.
    Ver docs/cuotas-y-reserva.md §3.2."""
    precio_total = gd.precio_contado()
    monto_reserva = gd.monto_reserva
    ahora = timezone.now()
    monto_inicial = max(monto_reserva - int(descuento_item or 0), 0)

    plan = PaymentPlan.objects.create(
        user=user,
        gamedetail=gd,
        tipo=PaymentPlan.TIPO_RESERVA,
        estado=PaymentPlan.ESTADO_ESPERANDO_STOCK,
        titulo_snapshot=_titulo_snapshot(gd),
        precio_total=precio_total,
        descuento=int(descuento_item or 0),
        monto_reserva=monto_reserva,
        total_pagado=monto_inicial,
        transaction_origen=transaction,
        fecha_creacion=ahora,
        fecha_actualizacion=ahora,
    )
    PaymentInstallment.objects.create(
        plan=plan, numero=1, monto=monto_inicial, mora=0,
        fecha_vencimiento=ahora.date(), estado=PaymentInstallment.ESTADO_PAGADA,
        fecha_pago=ahora, transaction=transaction, metodo="checkout",
    )
    PaymentInstallment.objects.create(
        plan=plan, numero=2, monto=max(precio_total - monto_reserva, 0), mora=0,
        fecha_vencimiento=None, estado=PaymentInstallment.ESTADO_PENDIENTE,
    )
    return plan


def transaction_tiene_planes(transaction):
    """True si el request original de esta transacción (el carrito del
    checkout) tenía algún ítem que no fuera de contado."""
    if not transaction or not transaction.request:
        return False
    try:
        data = json.loads(transaction.request)
    except (TypeError, ValueError):
        return False
    return any((item.get("modo_pago") or "contado") != "contado" for item in data.get("data", []))


def transaction_es_cuota(transaction):
    """True si esta transacción es el pago de una cuota siguiente (creada por
    planes/cuotaTransferenciaCreate/ o planes/cuotaBoldHash/), no un
    checkout normal."""
    if not transaction or not transaction.request:
        return False
    try:
        return json.loads(transaction.request).get("tipo") == "cuota"
    except (TypeError, ValueError):
        return False


def autoriza_por_plan_token(transaction, plan_token):
    """True si `plan_token` corresponde al plan dueño de la cuota que paga
    esta transacción -- usado como alternativa al JWT en
    transferencia_confirmar_envio/transferencia_status cuando la transacción
    es de tipo 'cuota' (ver docs/cuotas-y-reserva.md §4.4)."""
    if not plan_token or not transaction_es_cuota(transaction):
        return False
    try:
        plan_id = json.loads(transaction.request).get("plan_id")
    except (TypeError, ValueError):
        return False
    return PaymentPlan.objects.filter(pk=plan_id, token=plan_token).exists()


def _metodo_ventas(transaction):
    if transaction and transaction.payment_id == TRANSFERENCIA_PAYMENT_ID:
        return "TRANSFERENCIA_BREB"
    return "BOLD"


def _metodo_cuota(transaction):
    """Valor guardado en PaymentInstallment.metodo -- enum reducido
    ('transferencia_brebb' | 'bold' | 'manual' | 'checkout'), a diferencia de
    Transactions.payment_id que en Bold se sobreescribe con el franquicia de
    la tarjeta (ej. 'visa') apenas se aprueba el pago."""
    if transaction and transaction.payment_id == TRANSFERENCIA_PAYMENT_ID:
        return TRANSFERENCIA_PAYMENT_ID
    return "bold"


def item_ventas_contado(gd, monto):
    return {"modo_pago": "contado", "descripcion": str(gd), "monto": int(monto)}


def item_ventas_plan_inicial(plan, monto):
    item = {
        "modo_pago": plan.tipo,
        "plan_ref": f"PLAN-{plan.id}",
        "descripcion": plan.titulo_snapshot,
        "monto": int(monto),
        "evento": "inicial",
        "total_plan": plan.precio_total,
    }
    if plan.tipo == PaymentPlan.TIPO_CUOTAS:
        item["numero_cuota"] = 1
        item["num_cuotas"] = plan.num_cuotas
    return item


def _item_ventas_cuota_pagada(plan, cuota, evento):
    item = {
        "modo_pago": plan.tipo,
        "plan_ref": f"PLAN-{plan.id}",
        "descripcion": plan.titulo_snapshot,
        "monto": int(cuota.monto),
        "evento": evento,
        "total_plan": plan.precio_total,
    }
    if plan.tipo == PaymentPlan.TIPO_CUOTAS:
        item["numero_cuota"] = cuota.numero
        item["num_cuotas"] = plan.num_cuotas
    return item


def notificar_ventas_planes(transaction, items):
    """POST best-effort a hardcoregames-ventas con el evento de planes (spec
    §7). Nunca debe poder tumbar la confirmación real de la venta/cuota si
    falla -- misma filosofía que _notify_ventas_module en views.py."""
    if not items:
        return
    if transaction is None:
        logger.warning(
            "notificar_ventas_planes: sin transacción de origen, no se pudo notificar a ventas (items=%s)",
            items,
        )
        return
    try:
        payload = {
            "referencia_pago": transaction.id_invoice,
            "metodo": _metodo_ventas(transaction),
            "payer_email": transaction.user_id.email if transaction.user_id else "",
            "monto_total_pago": int(transaction.amount),
            "items": items,
        }
        headers = {"X-Planes-Token": VENTAS_PLANES_WEBHOOK_SECRET} if VENTAS_PLANES_WEBHOOK_SECRET else {}
        response = requests.post(VENTAS_PLANES_WEBHOOK_URL, json=payload, headers=headers, timeout=15)
        if not response.ok:
            logger.error(
                "Registro de plan en ventas falló (status=%s) para %s: %s",
                response.status_code, transaction.id_invoice, response.text[:300],
            )
    except Exception:
        logger.exception(
            "No se pudo notificar a ventas el evento de planes para %s",
            transaction.id_invoice if transaction else "?",
        )


def confirm_installment_payment(transaction):
    """Confirma el pago de una cuota siguiente (o el saldo de una reserva),
    ya verificado por el webhook correspondiente (Bold o transferencia). Ver
    docs/cuotas-y-reserva.md §4.4."""
    try:
        data = json.loads(transaction.request)
    except (TypeError, ValueError):
        logger.error("confirm_installment_payment: request no es JSON válido para %s", transaction.id_invoice)
        return False

    installment_id = data.get("installment_id")
    cuota = PaymentInstallment.objects.select_related("plan").filter(pk=installment_id).first()
    if not cuota:
        logger.error(
            "confirm_installment_payment: la cuota %s no existe (transacción %s)",
            installment_id, transaction.id_invoice,
        )
        return False

    plan = cuota.plan
    ahora = timezone.now()

    cuota.estado = PaymentInstallment.ESTADO_PAGADA
    cuota.fecha_pago = ahora
    cuota.transaction = transaction
    cuota.metodo = _metodo_cuota(transaction)
    cuota.save()

    plan.total_pagado = plan.total_pagado + cuota.monto
    plan.mora_acumulada = max(plan.mora_acumulada - cuota.mora, 0)

    completado = plan.total_pagado + plan.descuento >= plan.precio_total
    if completado:
        plan.estado = PaymentPlan.ESTADO_COMPLETADO
        evento = "completado"
    elif plan.tipo == PaymentPlan.TIPO_CUOTAS:
        hay_vencidas = plan.cuotas.filter(
            estado=PaymentInstallment.ESTADO_PENDIENTE, fecha_vencimiento__lt=ahora.date(),
        ).exists()
        plan.estado = PaymentPlan.ESTADO_EN_MORA if hay_vencidas else PaymentPlan.ESTADO_ACTIVO
        evento = "cuota"
    else:
        # Reserva sin completar con este pago: el flujo de asignación de
        # cuenta (cuenta_asignada_id, estado 'asignado') es fase 3 y todavía
        # no existe, así que el estado del plan no se toca aquí.
        evento = "saldo" if cuota.numero == 2 else "cuota"

    plan.fecha_actualizacion = ahora
    plan.save()

    # Entrega de la cuenta asignada al pagar el saldo de una reserva -- fase
    # 3 (la asignación en sí todavía no tiene UI/flujo). Dejado como no-op
    # defensivo: si algún día cuenta_asignada_id llega a existir, aquí es
    # donde se haría la entrega real (SaleDetail + descuento de stock).
    if (plan.tipo == PaymentPlan.TIPO_RESERVA and cuota.numero == 2
            and plan.cuenta_asignada_id and not plan.saledetail_id):
        pass

    try:
        emails_planes.enviar_correo_cuota_recibida(plan, cuota)
    except Exception:
        logger.exception("No se pudo enviar el correo de cuota recibida para el plan #%s", plan.pk)

    notificar_ventas_planes(transaction, [_item_ventas_cuota_pagada(plan, cuota, evento)])
    return True
