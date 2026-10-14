"""Facturación electrónica con Alegra (DIAN).

Se engancha al final de `confirm_sale` (products/views.py) y es *best effort*:
nunca puede tumbar la entrega del producto. Si Alegra falla, la fila
`AlegraInvoice` queda `pendiente` y `manage.py reintentar_facturas_alegra`
(cron) la reintenta; al agotar intentos queda `fallida` y se avisa por correo.

Reglas acordadas con el dueño:
  - Solo ventas de contado cuyo valor de productos (sin recargo de tarjeta,
    con descuentos aplicados) sea ESTRICTAMENTE mayor a ALEGRA_MIN_AMOUNT.
  - Una factura por compra, con una línea por producto; ítem genérico de Alegra.
  - Cliente: "Consumidor Final" (el checkout no pide documento).
  - El régimen del emisor es "No responsable de IVA": líneas sin impuesto.
  - Cuotas y reservas NO se facturan todavía.

Config por variables de entorno (hc-django.env):
  ALEGRA_ENABLED=1              interruptor general (apagado por defecto)
  ALEGRA_TOKEN                  token JWT de la integración (Bearer)
  ALEGRA_MODE=draft|stamp       draft = borrador sin emitir a la DIAN (por defecto)
                                stamp = emite factura electrónica real
  ALEGRA_MIN_AMOUNT=99980
  ALEGRA_ITEM_ID                id del ítem genérico "Producto digital" en Alegra
  ALEGRA_CLIENT_ID=1            id del contacto "Consumidor Final"
  ALEGRA_NUMBER_TEMPLATE_ID=15  numeración electrónica (prefijo HG)
  ALEGRA_FALLBACK_EMAIL         correo ficticio para cuando el del comprador sea inválido
                                (si no se define, esas facturas se emiten sin enviar correo)
  ALEGRA_MAX_ATTEMPTS=5
"""
import json
import logging
import os
import threading
from datetime import timedelta
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import close_old_connections, transaction as db_transaction
from django.utils import timezone

from products.models import AlegraInvoice
from utils.SendEmail import SendEmail

logger = logging.getLogger(__name__)

API_BASE = "https://api.alegra.com/api/v1"
TIMEOUT = 25
TZ = ZoneInfo("America/Bogota")
# Espera entre reintentos: tras el intento N se espera N * 5 min.
BACKOFF_MINUTES = 5


def _env(name, default=""):
    return os.getenv(name, default).strip()


def enabled():
    return _env("ALEGRA_ENABLED").lower() in ("1", "true", "yes") and bool(_env("ALEGRA_TOKEN"))


def stamp_mode():
    return _env("ALEGRA_MODE", "draft").lower() == "stamp"


def min_amount():
    return int(_env("ALEGRA_MIN_AMOUNT", "99980") or 99980)


def max_attempts():
    return int(_env("ALEGRA_MAX_ATTEMPTS", "5") or 5)


def _headers():
    return {"Authorization": f"Bearer {_env('ALEGRA_TOKEN')}", "Content-Type": "application/json"}


def items_facturables(ventas_items):
    """Líneas de contado con monto positivo (formato de planes.item_ventas_contado)."""
    return [
        {"descripcion": (i.get("descripcion") or "Producto digital")[:300], "monto": int(i["monto"])}
        for i in ventas_items or []
        if i.get("modo_pago") == "contado" and int(i.get("monto") or 0) > 0
    ]


# Valores que acepta Alegra Colombia (verificado contra la API): CASH, CREDIT_CARD,
# DEBIT_CARD, DEBIT_TRANSFER, CREDIT_TRANSFER, CHECK. Bold no distingue débito de
# crédito, así que las tarjetas van como CREDIT_CARD. Sistecrédito es financiado.
_TRANSFERENCIAS = ("pse", "nequi", "bancolombia", "transferencia", "breb", "daviplata", "boton")


def metodo_pago(tx):
    """Medio de pago de la factura según como pagó el cliente (transaction.payment_id)."""
    pid = str(getattr(tx, "payment_id", "") or "").strip().lower()
    if not pid:
        return "CASH"
    if "sistecredito" in pid:
        return "CREDIT_TRANSFER"
    if any(k in pid for k in _TRANSFERENCIAS):
        return "DEBIT_TRANSFER"
    if any(k in pid for k in ("visa", "master", "amex", "american", "diners", "card", "tarjeta", "credit")):
        return "CREDIT_CARD"
    if "debit" in pid:
        return "DEBIT_CARD"
    return "CASH"


def construir_payload(tx, items):
    hoy = timezone.now().astimezone(TZ).date().isoformat()
    payload = {
        "date": hoy,
        "dueDate": hoy,
        "client": {"id": int(_env("ALEGRA_CLIENT_ID", "1"))},
        "items": [
            {
                "id": int(_env("ALEGRA_ITEM_ID")),
                "description": it["descripcion"],
                "price": it["monto"],
                "quantity": 1,
            }
            for it in items
        ],
        "numberTemplate": {"id": int(_env("ALEGRA_NUMBER_TEMPLATE_ID", "15"))},
        "observations": f"Orden {tx.id_invoice} (transaccion {tx.pk})"[:500],
        "paymentForm": "CASH",
        "paymentMethod": metodo_pago(tx),
    }
    if stamp_mode():
        payload["status"] = "open"
        payload["stamp"] = {"generateStamp": True}
    else:
        payload["status"] = "draft"
    return payload


def registrar_venta(tx, ventas_items):
    """Punto de entrada desde confirm_sale. Decide si la venta se factura y, de
    ser así, crea la fila y dispara el envío en un hilo. Nunca lanza."""
    try:
        if tx is None or not enabled():
            return None
        items = items_facturables(ventas_items)
        total = sum(i["monto"] for i in items)
        if total <= min_amount():
            return None
        inv, created = AlegraInvoice.objects.get_or_create(
            transaction=tx, defaults={"monto": total, "items_json": json.dumps(items)},
        )
        if created:
            threading.Thread(target=_procesar_en_hilo, args=(inv.pk,), daemon=True).start()
        return inv
    except Exception:
        logger.exception("Alegra: no se pudo registrar la factura de la tx %s", getattr(tx, "pk", None))
        return None


def _procesar_en_hilo(inv_id):
    close_old_connections()
    try:
        procesar(inv_id)
    except Exception:
        logger.exception("Alegra: error inesperado procesando factura %s", inv_id)
    finally:
        close_old_connections()


def procesar(inv_id):
    """Un intento de facturación. Toma la fila con lock, así el hilo inmediato y
    el cron de reintentos no pueden facturar la misma venta a la vez."""
    with db_transaction.atomic():
        inv = (AlegraInvoice.objects.select_for_update(skip_locked=True)
               .select_related("transaction__user_id").filter(pk=inv_id).first())
        if inv is None or inv.estado != AlegraInvoice.ESTADO_PENDIENTE:
            return inv
        inv.intentos += 1
        try:
            payload = construir_payload(inv.transaction, json.loads(inv.items_json))
            resp = requests.post(f"{API_BASE}/invoices", json=payload, headers=_headers(), timeout=TIMEOUT)
            if resp.status_code >= 400:
                raise RuntimeError(f"Alegra {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            inv.alegra_id = str(data.get("id"))
            nt = data.get("numberTemplate") or {}
            inv.numero = f"{nt.get('prefix') or ''}{nt.get('number') or ''}" or None
            inv.estado = AlegraInvoice.ESTADO_EMITIDA if stamp_mode() else AlegraInvoice.ESTADO_BORRADOR
            inv.ultimo_error = ""
        except Exception as e:
            inv.ultimo_error = str(e)[:1000]
            logger.warning("Alegra: fallo intento %s de tx %s: %s", inv.intentos, inv.transaction_id, e)
            if inv.intentos >= max_attempts():
                inv.estado = AlegraInvoice.ESTADO_FALLIDA
        inv.fecha_actualizacion = timezone.now()
        inv.save()
    if inv.estado == AlegraInvoice.ESTADO_FALLIDA:
        _avisar_fallo(inv)
    elif inv.estado == AlegraInvoice.ESTADO_EMITIDA:
        _enviar_por_correo(inv)
    return inv


def _enviar_por_correo(inv):
    """Alegra le manda la factura al comprador. Si falla no afecta la factura."""
    try:
        email = (inv.transaction.user_id.email or "").strip()
        try:
            validate_email(email)
        except ValidationError:
            # Contador: si el correo es erróneo, enviarlo a un correo ficticio.
            email = _env("ALEGRA_FALLBACK_EMAIL")
            if not email:
                return
        resp = requests.post(
            f"{API_BASE}/invoices/{inv.alegra_id}/email",
            json={"emails": [email], "invoiceType": "NATIONAL"},
            headers=_headers(), timeout=TIMEOUT,
        )
        if resp.status_code >= 400:
            logger.warning("Alegra: no se pudo enviar la factura %s por correo: %s", inv.alegra_id, resp.text[:300])
    except Exception:
        logger.exception("Alegra: error enviando factura %s por correo", inv.alegra_id)


def _avisar_fallo(inv):
    try:
        html = (f"<html><body>La factura electrónica de la transacción {inv.transaction_id} "
                f"(${inv.monto:,}) falló {inv.intentos} veces y requiere revisión manual.<br>"
                f"Último error: {inv.ultimo_error}</body></html>")
        SendEmail().__int__(html, "Factura electrónica pendiente de revisión", settings.FROM_EMAIL)
    except Exception:
        logger.exception("Alegra: no se pudo enviar el aviso de fallo")


def reintentar_pendientes():
    """Para el cron. Reintenta pendientes con backoff lineal; devuelve cuántas tocó."""
    ahora = timezone.now()
    n = 0
    for inv in AlegraInvoice.objects.filter(estado=AlegraInvoice.ESTADO_PENDIENTE).order_by("id"):
        if inv.intentos and ahora - inv.fecha_actualizacion < timedelta(minutes=BACKOFF_MINUTES * inv.intentos):
            continue
        procesar(inv.pk)
        n += 1
    return n
