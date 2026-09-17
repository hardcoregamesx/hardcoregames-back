"""Bloques HTML de correo para Cuotas y Reserva (ver
docs/cuotas-y-reserva.md §4.6). Se inyectan dentro de `div#body` de la misma
plantilla que ya usa el resto de la tienda (`settings.EMAIL_FOR_SALE`), igual
que `build_div_html` en products/views.py -- así se reutiliza cabecera, pie
y soporte sin duplicar la plantilla completa.

Estilo en línea, colores de marca: fondo oscuro `#1a1030`, dorado `#f5c542`.
"""
import logging

from bs4 import BeautifulSoup
from django.conf import settings

from products.models import PaymentInstallment
from utils.SendEmail import SendEmail

logger = logging.getLogger(__name__)

DORADO = "#f5c542"
FONDO_OSCURO = "#1a1030"


def _formato_cop(monto):
    return f"${monto:,.0f}".replace(",", ".")


def _boton_ver_pagos(token):
    url = f"https://www.hardcoregames.co/pagos/{token}"
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:14px;">'
        f'<tr><td align="center" style="background-color:{DORADO};border-radius:5px;padding:10px 22px;">'
        f'<a href="{url}" style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:{FONDO_OSCURO};'
        'text-decoration:none;font-weight:700;" target="_blank">Ver mis pagos &#8594;</a></td></tr></table>'
    )


def bloque_plan_cuotas_creado(plan):
    """Bloque "Tu plan de cuotas" que se agrega al correo de compra cuando
    algún ítem del carrito se pagó a cuotas."""
    pendientes = plan.cuotas.filter(estado=PaymentInstallment.ESTADO_PENDIENTE).order_by("numero")
    filas = "".join(
        f'<li style="margin-bottom:6px;">Cuota {c.numero}/{plan.num_cuotas}: '
        f'{_formato_cop(c.monto)} COP &mdash; vence '
        f'{c.fecha_vencimiento.strftime("%d/%m/%Y") if c.fecha_vencimiento else "por definir"}</li>'
        for c in pendientes
    )
    return f'''<div style="margin-bottom:20px;">
       <h3 style="color:{DORADO};margin-bottom:8px;">Tu plan de cuotas</h3>
       <p style="margin:0 0 8px;"><b>{plan.titulo_snapshot}</b></p>
       <p style="margin:0 0 8px;">Ya pagaste la cuota inicial y tu producto quedó entregado arriba.
       Las siguientes cuotas vencen cada 30 días:</p>
       <ul style="margin:0 0 8px;padding-left:20px;">{filas}</ul>
       {_boton_ver_pagos(plan.token)}
    </div>
    <hr style="border-color:#e0e0e0;border-width:1px">'''


def bloque_reserva_confirmada(plan):
    """Bloque/correo "Reserva confirmada" -- no hay credenciales que mostrar
    (nada se entrega todavía), así que este bloque se manda en su propio
    correo (ver enviar_correo_reserva_confirmada)."""
    producto = plan.gamedetail.producto if plan.gamedetail else None
    fecha_lanzamiento = producto.fecha_lanzamiento if producto else None
    fecha_txt = fecha_lanzamiento.strftime("%d/%m/%Y") if fecha_lanzamiento else "por confirmar"
    saldo = max(plan.precio_total - (plan.monto_reserva or 0), 0)
    return f'''<div style="margin-bottom:20px;">
       <h3 style="color:{DORADO};margin-bottom:8px;">Reserva confirmada</h3>
       <p style="margin:0 0 8px;"><b>{plan.titulo_snapshot}</b></p>
       <p style="margin:0 0 8px;">Tu reserva quedó registrada con un pago de
       {_formato_cop(plan.monto_reserva or 0)} COP. Sale el {fecha_txt}.</p>
       <p style="margin:0 0 8px;">No se entrega nada todavía: cuando asignemos tu cuenta te
       pediremos el saldo de {_formato_cop(saldo)} COP.</p>
       {_boton_ver_pagos(plan.token)}
    </div>
    <hr style="border-color:#e0e0e0;border-width:1px">'''


def bloque_cuota_recibida(plan, cuota):
    """Bloque/correo "Cuota N de M recibida" tras confirmar el pago de una
    cuota siguiente (ver planes.confirm_installment_payment)."""
    pendientes = plan.cuotas.filter(estado=PaymentInstallment.ESTADO_PENDIENTE).order_by("numero")
    if pendientes.exists():
        siguiente = pendientes.first()
        vence_txt = (
            siguiente.fecha_vencimiento.strftime("%d/%m/%Y")
            if siguiente.fecha_vencimiento else "cuando asignemos tu cuenta"
        )
        resto_txt = f"Te queda{'n' if pendientes.count() != 1 else ''} {pendientes.count()} pago(s) pendiente(s). El próximo vence {vence_txt}."
    else:
        resto_txt = "Con este pago tu plan quedó completado. ¡Gracias por tu compra!"

    if plan.tipo == 'reserva':
        titulo = "Saldo recibido" if cuota.numero == 2 else "Pago de reserva recibido"
    else:
        titulo = f"Cuota {cuota.numero} de {plan.num_cuotas} recibida"

    return f'''<div style="margin-bottom:20px;">
       <h3 style="color:{DORADO};margin-bottom:8px;">{titulo}</h3>
       <p style="margin:0 0 8px;"><b>{plan.titulo_snapshot}</b></p>
       <p style="margin:0 0 8px;">Recibimos {_formato_cop(cuota.monto)} COP. {resto_txt}</p>
       {_boton_ver_pagos(plan.token)}
    </div>
    <hr style="border-color:#e0e0e0;border-width:1px">'''


def _enviar(email_to, html_block, subject):
    if not email_to:
        return
    try:
        soup = BeautifulSoup(settings.EMAIL_FOR_SALE, features="html.parser")
        extra_soup = BeautifulSoup(html_block, "html.parser")
        body = soup.find(id="body") or soup
        body.append(extra_soup)
        SendEmail().__int__(str(soup), subject, email_to)
    except Exception:
        logger.exception("No se pudo enviar el correo de planes (%s) a %s", subject, email_to)


def enviar_correo_reserva_confirmada(user, plan):
    email_to = user.email if user else None
    _enviar(email_to, bloque_reserva_confirmada(plan), "Reserva confirmada en Hardcore Games")


def enviar_correo_cuota_recibida(plan, cuota):
    email_to = plan.user.email if plan.user else None
    if plan.tipo == 'reserva':
        subject = "Saldo recibido" if cuota.numero == 2 else "Pago de reserva recibido"
    else:
        subject = f"Cuota {cuota.numero} de {plan.num_cuotas} recibida"
    _enviar(email_to, bloque_cuota_recibida(plan, cuota), f"{subject} — Hardcore Games")
