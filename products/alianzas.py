"""Beneficios aliados: un cliente con una compra aprobada en el mes (hora de
Colombia) desbloquea los codigos de los negocios aliados de ese mes.

El desbloqueo no se guarda: se calcula al consultar a partir de las compras
aprobadas, asi que un pago revertido o una reserva cancelada lo revoca solo.
El codigo tampoco se guarda: sale de una regla que el aliado puede aplicar
con calculadora (ver `codigo_del_mes`).
"""
import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Bogota")

ESTADOS_PAGO_APROBADO = ("approved", "SALE_APPROVED")
ESTADOS_PLAN_REVOCADOS = ("cancelado", "retirado")


def _letras(nombre):
    sin_tildes = unicodedata.normalize("NFKD", nombre or "")
    return re.sub(r"[^A-Za-z]", "", sin_tildes.encode("ascii", "ignore").decode()).upper()


def codigo_del_mes(aliado, mes):
    """`mes` es un date (cualquier dia del mes). Regla: primera y ultima letra
    del nombre del negocio, un guion y los ultimos 4 digitos de
    secreto x numero del mes. Ej.: "Deportes", secreto 417, octubre ->
    417 x 10 = 4170 -> "DS-4170". Si el aliado tiene `codigo_fijo`, gana."""
    if aliado.codigo_fijo:
        return aliado.codigo_fijo
    letras = _letras(aliado.nombre)
    if not letras:
        raise ValueError("El nombre del aliado no tiene letras")
    return f"{letras[0]}{letras[-1]}-{(aliado.secreto * mes.month) % 10000:04d}"


def hoy_colombia(ahora=None):
    return (ahora or datetime.now(TZ)).astimezone(TZ).date()


def _primer_dia(d):
    return d.replace(day=1)


def _mes_siguiente(d):
    return (_primer_dia(d) + timedelta(days=32)).replace(day=1)


def _rango_mes_utc(primer_dia):
    inicio = datetime(primer_dia.year, primer_dia.month, 1, tzinfo=TZ)
    fin_dia = _mes_siguiente(primer_dia)
    fin = datetime(fin_dia.year, fin_dia.month, 1, tzinfo=TZ)
    return inicio, fin


def _compras_calificadas(user, inicio, fin):
    """Compras aprobadas del usuario en [inicio, fin). Una reserva o cuota
    inicial cuenta como compra; si el plan de esa transaccion fue cancelado o
    retirado, la transaccion deja de contar."""
    from products.models import Transactions

    transacciones = Transactions.objects.filter(
        user_id=user, status__in=ESTADOS_PAGO_APROBADO,
        date_transaction__gte=inicio, date_transaction__lt=fin,
    )
    for t in transacciones:
        planes = list(t.planes_originados.all())
        if planes and all(p.estado in ESTADOS_PLAN_REVOCADOS for p in planes):
            continue
        return True
    return False


def usuario_desbloqueado(user, hoy=None):
    """True si `user` (cuenta con registro completo) tiene los beneficios del
    mes en curso. Compra el ultimo dia del mes anterior tambien cuenta."""
    perfil = getattr(user, "user_customized", None)
    if perfil is None or perfil.is_guest_account:
        return False
    hoy = hoy or hoy_colombia()
    inicio, fin = _rango_mes_utc(_primer_dia(hoy))
    if _compras_calificadas(user, inicio, fin):
        return True
    ultimo_dia_previo = _primer_dia(hoy) - timedelta(days=1)
    inicio_prev = datetime(ultimo_dia_previo.year, ultimo_dia_previo.month, ultimo_dia_previo.day, tzinfo=TZ)
    return _compras_calificadas(user, inicio_prev, inicio_prev + timedelta(days=1))


def fin_de_mes(hoy=None):
    hoy = hoy or hoy_colombia()
    return _mes_siguiente(hoy) - timedelta(days=1)


def beneficios_para(user, hoy=None):
    """Lista para el frontend. El codigo solo viaja si `user` esta desbloqueado."""
    from products.models import Aliado

    hoy = hoy or hoy_colombia()
    desbloqueado = usuario_desbloqueado(user, hoy)
    vence = fin_de_mes(hoy).isoformat()
    resultado = []
    for a in Aliado.objects.filter(activo=True).order_by("orden", "nombre"):
        item = {
            "id": a.id, "nombre": a.nombre, "categoria": a.categoria,
            "logo_url": a.logo_url, "beneficio": a.beneficio,
            "condiciones": a.condiciones, "desbloqueado": desbloqueado,
            "vence": vence if desbloqueado else None,
            "codigo": codigo_del_mes(a, hoy) if desbloqueado else None,
        }
        resultado.append(item)
    return resultado


def bloque_correo():
    """HTML que se agrega al correo de confirmacion de compra. Vacio mientras
    el lanzamiento no este abierto (ALIANZAS_ABIERTO=1) o no haya aliados."""
    import os

    from products.models import Aliado

    if os.environ.get("ALIANZAS_ABIERTO") != "1" or not Aliado.objects.filter(activo=True).exists():
        return ""
    return (
        '<div style="margin:24px 0;padding:16px;border-radius:12px;background:#f4f1ff;text-align:center">'
        '<p style="margin:0 0 8px;font-size:16px;font-weight:bold">&iexcl;Desbloqueaste tus beneficios del mes!</p>'
        '<p style="margin:0 0 12px">Descuentos en negocios aliados, solo para clientes de Hardcore Games.</p>'
        '<a href="https://www.hardcoregames.co/beneficios" style="display:inline-block;padding:10px 20px;'
        'border-radius:8px;background:#6d28d9;color:#fff;text-decoration:none">Ver mis beneficios</a>'
        '</div>'
    )
