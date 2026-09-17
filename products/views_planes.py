"""Endpoints de "Cuotas y Reserva" para pagar cuotas siguientes (ver
docs/cuotas-y-reserva.md §4.4). Montados bajo `products/planes/` en
products/urls.py.

Reutiliza a propósito las piezas ya probadas de products/views.py
(parseo de request, firma/hash de Bold, llamada a pagos-nequi, JWT) en vez de
reimplementarlas -- la lógica de dominio (armar el plan, confirmar el pago)
vive en products/planes.py."""
import json

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from products import views
from products.models import PaymentInstallment, Transactions


def _autorizar(request, data, plan):
    """JWT Bearer (dueño del plan o superusuario) O planToken que coincida
    con el del plan -- nunca ambos obligatorios (ver spec §4.4)."""
    plan_token = data.get("planToken") or request.GET.get("planToken")
    if plan_token and plan_token == plan.token:
        return True
    token_user_id, is_superuser = views._get_verified_jwt_user(request)
    if token_user_id is not None and (is_superuser or token_user_id == plan.user_id):
        return True
    return False


def _validar_cuota_pagable(plan, cuota):
    """La cuota debe seguir pendiente y ser la más antigua pendiente del
    plan -- no se puede pagar la 3 antes que la 2."""
    if cuota.estado != PaymentInstallment.ESTADO_PENDIENTE:
        return "Esta cuota ya no está pendiente"
    mas_antigua = plan.cuotas.filter(estado=PaymentInstallment.ESTADO_PENDIENTE).order_by("numero").first()
    if not mas_antigua or mas_antigua.pk != cuota.pk:
        return "Debes pagar primero la cuota pendiente más antigua"
    return None


@csrf_exempt
def cuota_transferencia_create(request):
    """POST planes/cuotaTransferenciaCreate/
    body: {installment_id, nombre_pagador, planToken?}
    Respuesta: mismo shape que transferencia_create
    ({transactionId, amount, breBKey, deadlineAt})."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    data = views.parse_request_data(request)
    if not data:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    installment_id = data.get("installment_id")
    nombre_pagador = (data.get("nombre_pagador") or "").strip()
    if not installment_id or not nombre_pagador:
        return JsonResponse({"error": "Faltan datos de la cuota o el nombre del pagador"}, status=400)

    cuota = PaymentInstallment.objects.select_related("plan").filter(pk=installment_id).first()
    if not cuota:
        return JsonResponse({"error": "Cuota no encontrada"}, status=404)
    plan = cuota.plan

    if not _autorizar(request, data, plan):
        return JsonResponse({"error": "No autorizado"}, status=403)

    error = _validar_cuota_pagable(plan, cuota)
    if error:
        return JsonResponse({"error": error}, status=400)

    monto = cuota.monto + cuota.mora
    order_id = views.generate_order_id()
    stored_request = json.dumps({
        "tipo": "cuota",
        "installment_id": cuota.pk,
        "plan_id": plan.pk,
        "id_user": plan.user_id,
        "nombre_pagador": nombre_pagador,
    })

    transaction = Transactions.objects.create(
        status="pendiente",
        amount=monto,
        payment_id=views.TRANSFERENCIA_PAYMENT_ID,
        ref_payco=order_id,
        id_invoice=order_id,
        request=stored_request,
        user_id=plan.user,
    )

    registered = views._pagos_nequi_call("POST", "/api/expectations", {
        "transaction_id": order_id,
        "nombre_pagador": nombre_pagador,
        "monto_cop": monto,
    })
    if registered is None:
        transaction.status = "failed"
        transaction.save()
        return JsonResponse({"error": "No se pudo iniciar la verificacion del pago, intenta de nuevo"}, status=502)

    return JsonResponse({
        "transactionId": order_id,
        "amount": monto,
        "breBKey": views._get_breb_key(),
        "deadlineAt": registered.get("deadline_at"),
    }, status=200)


@csrf_exempt
def cuota_bold_hash(request):
    """POST planes/cuotaBoldHash/
    body: {installment_id, amount, currency, planToken?}
    Equivalente a generate_hash_bold: acepta el monto exacto de la cuota (con
    mora si aplica) o ese monto + la tarifa de tarjeta de Bold."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    data = views.parse_request_data(request)
    if not data:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    installment_id = data.get("installment_id")
    amount = data.get("amount")
    currency = data.get("currency")
    if not installment_id or not amount or not currency:
        return JsonResponse({"error": "Missing required fields"}, status=400)

    cuota = PaymentInstallment.objects.select_related("plan").filter(pk=installment_id).first()
    if not cuota:
        return JsonResponse({"error": "Cuota no encontrada"}, status=404)
    plan = cuota.plan

    if not _autorizar(request, data, plan):
        return JsonResponse({"error": "No autorizado"}, status=403)

    error = _validar_cuota_pagable(plan, cuota)
    if error:
        return JsonResponse({"error": error}, status=400)

    calculated_amount = cuota.monto + cuota.mora
    try:
        received_amount = int(amount)
    except (TypeError, ValueError):
        return JsonResponse({"error": "amount inválido"}, status=400)

    amount_with_card_fee = calculated_amount + views._compute_card_fee(calculated_amount)
    if received_amount == calculated_amount:
        final_amount = calculated_amount
    elif received_amount == amount_with_card_fee:
        final_amount = amount_with_card_fee
    else:
        return JsonResponse({"error": "El monto no coincide con la cuota"}, status=400)

    order_id = views.generate_order_id()
    signature = views.generate_signature(order_id, final_amount, currency, settings.SECRET_KEY_BOLD)
    stored_request = json.dumps({
        "tipo": "cuota",
        "installment_id": cuota.pk,
        "plan_id": plan.pk,
        "id_user": plan.user_id,
    })

    Transactions.objects.create(
        status="pendiente",
        amount=final_amount,
        payment_id="bold",
        ref_payco=order_id,
        id_invoice=order_id,
        request=stored_request,
        user_id=plan.user,
    )

    payload = views.build_payload(order_id, signature)
    return JsonResponse(payload, status=200)
