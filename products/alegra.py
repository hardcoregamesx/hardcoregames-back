"""Facturación electrónica con Alegra (DIAN).

Se engancha al final de `confirm_sale` (products/views.py) y es *best effort*:
nunca puede tumbar la entrega del producto. Si Alegra falla, la fila
`AlegraInvoice` queda `pendiente` y `manage.py reintentar_facturas_alegra`
(cron) la reintenta; al agotar intentos queda `fallida` y se avisa por correo.

Reglas acordadas con el dueño:
  - Solo ventas de contado. Se factura si el valor de productos (sin recargo de
    tarjeta, con descuentos aplicados) es ESTRICTAMENTE mayor a ALEGRA_MIN_AMOUNT
    O si el cliente marcó "requiero factura electrónica" en el checkout.
  - Una factura por compra, con una línea por producto; ítem genérico de Alegra.
  - Cliente: el que el comprador declaró en el checkout (`facturacion` dentro de
    Transactions.request: tipo_doc, numero, nombre, email); si no pidió factura,
    "Consumidor Final".
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
  ALEGRA_EMISOR_NIT=1114456688-9    NIT que se muestra al cliente para consultar la factura en la DIAN
  ALEGRA_ITEM_REFERENCE=HG-DIGITAL  código del producto en cada línea (regla FAZ09 de la DIAN)
  ALEGRA_FALLBACK_EMAIL         correo para cuando el del comprador sea inválido
                                (si no se define, no se envía el correo de la factura)
  ALEGRA_MAX_ATTEMPTS=5
"""
import json
import logging
import os
import smtplib
import threading
from datetime import timedelta
from email.message import EmailMessage
from html import escape
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


TIPOS_DOC = {"CC", "NIT", "CE", "PP"}
# Alegra rechaza la emisión si el contacto no tiene régimen fiscal ("requerido
# cuando el tipo de identificación es CC"). Los borradores no validan esto.
REGIMEN_PERSONA = "SIMPLIFIED_REGIME"
REGIMEN_EMPRESA = "COMMON_REGIME"


def normalizar_facturacion(raw):
    """Datos de facturación que escribe el comprador: llegan del navegador, así
    que se validan y se reducen a las 4 claves conocidas. Devuelve None si no
    pidió factura o si los datos no son válidos (en ese caso se factura como
    Consumidor Final, nunca se rompe el pago)."""
    if not isinstance(raw, dict):
        return None
    tipo = str(raw.get("tipo_doc") or "").strip().upper()
    numero = "".join(ch for ch in str(raw.get("numero") or "") if ch.isdigit())
    nombre = " ".join(str(raw.get("nombre") or "").split())[:120]
    apellidos = " ".join(str(raw.get("apellidos") or "").split())[:120]
    email = str(raw.get("email") or "").strip()[:120]
    if tipo not in TIPOS_DOC or not (5 <= len(numero) <= 15) or len(nombre) < 2:
        return None
    if tipo != "NIT":
        # Alegra exige nombres y apellidos por separado para personas naturales.
        # Si el cliente puso todo en un solo campo, el último término es el apellido.
        if not apellidos:
            partes = nombre.split()
            if len(partes) < 2:
                return None
            nombre, apellidos = " ".join(partes[:-1]), partes[-1]
    else:
        apellidos = ""
    try:
        validate_email(email)
    except ValidationError:
        email = ""
    return {"tipo_doc": tipo, "numero": numero, "nombre": nombre, "apellidos": apellidos, "email": email}


def facturacion_de(tx_request):
    """Extrae y valida `facturacion` del JSON guardado en Transactions.request."""
    try:
        data = json.loads(tx_request) if isinstance(tx_request, (str, bytes)) else (tx_request or {})
    except (TypeError, ValueError):
        return None
    return normalizar_facturacion(data.get("facturacion") if isinstance(data, dict) else None)


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


def construir_payload(tx, items, client_id=None):
    hoy = timezone.now().astimezone(TZ).date().isoformat()
    payload = {
        "date": hoy,
        "dueDate": hoy,
        "client": {"id": int(client_id or _env("ALEGRA_CLIENT_ID", "1"))},
        "items": [
            {
                "id": int(_env("ALEGRA_ITEM_ID")),
                "reference": _env("ALEGRA_ITEM_REFERENCE", "HG-DIGITAL")[:45],
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


def registrar_venta(tx, ventas_items, facturacion=None):
    """Punto de entrada desde confirm_sale. Decide si la venta se factura y, de
    ser así, crea la fila y dispara el envío en un hilo. Nunca lanza.
    `facturacion` son los datos que el comprador declaró en el checkout."""
    try:
        if tx is None or not enabled():
            return None
        items = items_facturables(ventas_items)
        total = sum(i["monto"] for i in items)
        pidio_factura = normalizar_facturacion(facturacion) is not None
        if total <= 0 or (total <= min_amount() and not pidio_factura):
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


def cliente_alegra(facturacion):
    """id del contacto de Alegra para el comprador. Sin datos -> Consumidor Final.
    Con datos: busca por número de identificación y, si no existe, lo crea."""
    if not facturacion:
        return int(_env("ALEGRA_CLIENT_ID", "1"))
    numero = facturacion["numero"]
    es_empresa = facturacion["tipo_doc"] == "NIT"
    regimen = REGIMEN_EMPRESA if es_empresa else REGIMEN_PERSONA
    r = requests.get(f"{API_BASE}/contacts", params={"identification": numero, "limit": 5},
                     headers=_headers(), timeout=TIMEOUT)
    if r.status_code < 300:
        for c in r.json() or []:
            # NIT llega como "900123456-7": se compara solo la parte antes del DV.
            if str(c.get("identification") or "").split("-")[0] == numero:
                if not c.get("regime"):
                    _poner_regimen(c, regimen)
                return int(c["id"])
    body = {
        "regime": regimen,
        "identificationObject": {"type": facturacion["tipo_doc"], "number": numero},
        "kindOfPerson": "LEGAL_ENTITY" if es_empresa else "PERSON_ENTITY",
        "type": ["client"],
    }
    if es_empresa:
        body["name"] = facturacion["nombre"]  # razón social
    else:
        nombres, apellidos = facturacion["nombre"].split(), facturacion["apellidos"].split()
        body["nameObject"] = {
            "firstName": nombres[0], "secondName": " ".join(nombres[1:]),
            "lastName": apellidos[0], "secondLastName": " ".join(apellidos[1:]),
        }
    if facturacion["email"]:
        body["email"] = facturacion["email"]
    r = requests.post(f"{API_BASE}/contacts", json=body, headers=_headers(), timeout=TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"Alegra contacto {r.status_code}: {r.text[:400]}")
    return int(r.json()["id"])


def _poner_regimen(contacto, regimen):
    """Contactos creados antes de este arreglo no tienen régimen. Alegra exige
    reenviar el nombre en el PUT, así que se manda el que ya tiene el contacto."""
    body = {"regime": regimen}
    if contacto.get("nameObject"):
        body["nameObject"] = contacto["nameObject"]
    else:
        body["name"] = contacto.get("name")
    r = requests.put(f"{API_BASE}/contacts/{contacto['id']}", json=body, headers=_headers(), timeout=TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"Alegra régimen del contacto {contacto['id']} {r.status_code}: {r.text[:300]}")


def _descartar_factura_huerfana(resp):
    """Cuando Alegra crea la factura pero no puede emitirla, responde 400 con la
    factura creada (sin emitir). Si no se borra, cada reintento deja una más.
    Solo se borra si de verdad quedó sin emitir."""
    try:
        inv = (resp.json() or {}).get("invoice") or {}
        legal = (inv.get("stamp") or {}).get("legalStatus") or ""
        if inv.get("id") and not legal.startswith("STAMPED"):
            requests.delete(f"{API_BASE}/invoices/{inv['id']}", headers=_headers(), timeout=TIMEOUT)
    except Exception:
        logger.exception("Alegra: no se pudo descartar la factura sin emitir")


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
            client_id = cliente_alegra(facturacion_de(inv.transaction.request))
            payload = construir_payload(inv.transaction, json.loads(inv.items_json), client_id)
            resp = requests.post(f"{API_BASE}/invoices", json=payload, headers=_headers(), timeout=TIMEOUT)
            if resp.status_code >= 400:
                _descartar_factura_huerfana(resp)
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
        _notificar_comprador(inv)
    return inv


DIAN_CONSULTA = "https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey="


def _notificar_comprador(inv):
    """Alegra ya le envía la factura por correo al cliente cuando la factura lleva
    sus datos (verificado en los eventos CLIENT_EMAILS). Quien compra sin pedir
    factura sale a "Consumidor Final", que no tiene correo: a ese comprador se la
    mandamos nosotros desde la tienda. El token de Alegra no puede usar su endpoint
    de correo (403), por eso no se intenta. Si falla no afecta la factura."""
    try:
        if facturacion_de(inv.transaction.request):
            return
        email = (inv.transaction.user_id.email or "").strip()
        try:
            validate_email(email)
        except ValidationError:
            email = _env("ALEGRA_FALLBACK_EMAIL")
            if not email:
                return
        resp = requests.get(f"{API_BASE}/invoices/{inv.alegra_id}", params={"fields": "xml"},
                            headers=_headers(), timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        cufe = (data.get("stamp") or {}).get("cufe") or ""
        xml = b""
        if data.get("xml"):
            # El XML es un adjunto extra: si no se puede bajar, el correo sale igual
            # con el número, el CUFE y el enlace de la DIAN.
            try:
                xml_resp = requests.get(data["xml"], timeout=TIMEOUT)
                if xml_resp.ok:
                    xml = xml_resp.content
            except requests.RequestException:
                logger.warning("Alegra: no se pudo bajar el XML de la factura %s", inv.alegra_id)
        numero = inv.numero or (data.get("numberTemplate") or {}).get("fullNumber") or ""
        _enviar_correo_factura(email, numero, inv.monto, data.get("date"), json.loads(inv.items_json), cufe, xml)
    except Exception:
        logger.exception("Alegra: no se pudo enviar al comprador la factura %s", inv.alegra_id)


def _cop(n):
    return "$" + f"{int(n):,}".replace(",", ".")


def _enviar_correo_factura(destino, numero, monto, fecha, items, cufe, xml):
    filas = "".join(f"<li>{escape(i['descripcion'])} — {_cop(i['monto'])}</li>" for i in items)
    nit = _env("ALEGRA_EMISOR_NIT", "1114456688-9")
    enlace = f"{DIAN_CONSULTA}{cufe}" if cufe else ""
    cuerpo_enlace = (
        f'<p>Para consultarla o descargarla en la DIAN entra a <a href="{enlace}">{enlace}</a> y escribe el CUFE '
        f"y el NIT del emisor: <strong>{escape(nit)}</strong>.</p>" if enlace else "")
    html = (f"<html><body><p>Gracias por tu compra en Hardcore Games. Esta es tu factura electrónica "
            f"<strong>{escape(str(numero))}</strong> del {escape(str(fecha or ''))} por "
            f"<strong>{_cop(monto)}</strong>.</p><ul>{filas}</ul>{cuerpo_enlace}"
            f"<p>También adjuntamos el archivo XML de la factura.</p><p>CUFE: {escape(cufe)}</p></body></html>")
    msg = EmailMessage()
    msg["From"] = settings.FROM_EMAIL
    msg["To"] = destino
    msg["Subject"] = f"Tu factura electrónica {numero} - Hardcore Games"
    msg.set_content("Tu factura electrónica de Hardcore Games está disponible en la versión HTML de este correo.")
    msg.add_alternative(html, subtype="html")
    if xml:
        msg.add_attachment(xml, maintype="application", subtype="xml", filename=f"{numero or 'factura'}.xml")
    smtp = smtplib.SMTP_SSL("smtp.gmail.com")
    try:
        smtp.login(settings.FROM_EMAIL, settings.PASS_SMTP)
        smtp.send_message(msg)
    finally:
        smtp.quit()


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
