import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import services
from .models import (
    ENVIO_DIRECTO, ENVIO_INTERMEDIA, ESTADO_RESERVADA, FUENTE_CHOICES, CiudadIntermedia, Pago, Preventa, Reserva,
)

FUENTES_VALIDAS = {f[0] for f in FUENTE_CHOICES}
MAX_UNIDADES = 100  # tope técnico anti-abuso; no es un límite de negocio


def _body(request):
    try:
        data = json.loads(request.body or b'{}')
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _preventa_public(p):
    info = services.fase_info(p)
    return {
        'slug': p.slug, 'title': p.title, 'description': p.description, 'imageUrl': p.image_url,
        'reservaUnit': p.reserva_unit, 'envioNacionalEst': p.envio_nacional_est,
        'fase': info['fase'], 'min': info['min'], 'max': info['max'], 'final': info['final'],
        'agotado': info['agotado'], 'disponibles': info['disponibles'],
        'switchAt': p.switch_at.isoformat() if p.switch_at else None,
    }


def _ciudades():
    return [
        {'nombre': c.nombre, 'costoEstimado': c.costo_estimado}
        for c in CiudadIntermedia.objects.filter(activa=True)
    ]


def preventas_list(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    services.expirar_vencidas()
    items = [_preventa_public(p) for p in Preventa.objects.filter(active=True).order_by('-created_at')]
    return JsonResponse({'preventas': items})


def preventa_detail(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    services.expirar_vencidas()
    p = Preventa.objects.filter(slug=request.GET.get('slug', ''), active=True).first()
    if not p:
        return JsonResponse({'error': 'Preventa no encontrada'}, status=404)
    return JsonResponse({'preventa': _preventa_public(p), 'ciudadesIntermedias': _ciudades()})


def _validar(data, preventa):
    err = {}
    nombre = str(data.get('nombre') or '').strip()
    whatsapp = services.solo_digitos(data.get('whatsapp'))
    direccion = str(data.get('direccion') or '').strip()
    ciudad = str(data.get('ciudad') or '').strip()
    cedula = services.solo_digitos(data.get('cedula'))
    fuente = str(data.get('fuente') or '').strip()
    envio_tipo = str(data.get('envioTipo') or ENVIO_DIRECTO)
    ciudad_int = str(data.get('ciudadIntermedia') or '').strip()
    nombre_pagador = str(data.get('nombrePagador') or '').strip() or nombre
    try:
        unidades = int(data.get('unidades'))
    except (TypeError, ValueError):
        unidades = 0

    if len(nombre) < 3:
        err['nombre'] = 'Escribe tu nombre completo'
    if not (10 <= len(whatsapp) <= 13):
        err['whatsapp'] = 'WhatsApp inválido'
    if len(direccion) < 5:
        err['direccion'] = 'Escribe tu dirección'
    if len(ciudad) < 2:
        err['ciudad'] = 'Escribe tu ciudad'
    if not (5 <= len(cedula) <= 12):
        err['cedula'] = 'Cédula inválida'
    if fuente not in FUENTES_VALIDAS:
        err['fuente'] = 'Selecciona cómo nos conociste'
    if not (1 <= unidades <= MAX_UNIDADES):
        err['unidades'] = 'Cantidad inválida'
    if envio_tipo not in (ENVIO_DIRECTO, ENVIO_INTERMEDIA):
        err['envioTipo'] = 'Tipo de envío inválido'
    elif envio_tipo == ENVIO_INTERMEDIA:
        if not CiudadIntermedia.objects.filter(activa=True, nombre=ci_name(ciudad_int)).exists():
            err['ciudadIntermedia'] = 'Selecciona una ciudad intermedia disponible'
    else:
        ciudad_int = ''
    if err:
        return None, err
    return {
        'nombre': nombre, 'whatsapp': whatsapp, 'direccion': direccion, 'ciudad': ciudad,
        'cedula': cedula, 'fuente': fuente, 'envio_tipo': envio_tipo,
        'ciudad_intermedia': ciudad_int, 'unidades': unidades, 'nombre_pagador': nombre_pagador,
    }, None


def ci_name(value):
    return value.strip()


@csrf_exempt
def reservar(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    data = _body(request)
    services.expirar_vencidas()
    p = Preventa.objects.filter(slug=str(data.get('slug') or ''), active=True).first()
    if not p:
        return JsonResponse({'error': 'Preventa no encontrada'}, status=404)
    datos, err = _validar(data, p)
    if err:
        return JsonResponse({'error': 'Revisa los datos', 'fields': err}, status=400)
    try:
        reserva, pago = services.crear_reserva(p, datos)
    except services.ReservaError as e:
        return JsonResponse({'error': e.message}, status=e.status)
    return JsonResponse({
        'codigo': reserva.codigo, 'unidades': reserva.unidades, 'reservaTotal': reserva.reserva_total,
        'pago': services.pago_payload(pago),
    }, status=201)


def _reserva_autorizada(data):
    codigo = str(data.get('codigo') or '').strip().upper()
    cedula = services.solo_digitos(data.get('cedula'))
    if not codigo or not cedula:
        return None
    r = Reserva.objects.select_related('preventa').filter(codigo=codigo).first()
    if r and r.cedula == cedula:
        return r
    return None


def _reserva_public(r):
    p = r.preventa
    s = services.saldo_info(r)
    pago_pend = r.pagos.filter(status='pendiente').order_by('-created_at').first()
    return {
        'codigo': r.codigo, 'estado': r.estado, 'fase': r.fase, 'unidades': r.unidades,
        'preventa': {'slug': p.slug, 'title': p.title, 'imageUrl': p.image_url},
        'nombre': r.nombre, 'ciudad': r.ciudad, 'cedula': services.mask_cedula(r.cedula),
        'envioTipo': r.envio_tipo, 'ciudadIntermedia': r.ciudad_intermedia,
        'envioEstimado': p.envio_nacional_est if r.envio_tipo == ENVIO_DIRECTO else None,
        'reservaTotal': r.reserva_total, 'reservaPagada': bool(r.paid_at),
        'saldo': {
            'definitivo': s['definitivo'], 'precioUnit': s['precio_unit'], 'monto': s['saldo'],
            'min': s['saldo_min'], 'max': s['saldo_max'],
            'puedePagar': r.estado == ESTADO_RESERVADA and s['definitivo'] and (s['saldo'] or 0) > 0,
        },
        'guia': r.guia, 'despachadoAt': r.despachado_at.isoformat() if r.despachado_at else None,
        'expiresAt': r.expires_at.isoformat() if r.expires_at else None,
        'pagoPendiente': services.pago_payload(pago_pend) if pago_pend else None,
    }


@csrf_exempt
def consulta(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    services.expirar_vencidas()
    r = _reserva_autorizada(_body(request))
    if not r:
        return JsonResponse({'error': 'No encontramos una reserva con ese código y cédula'}, status=404)
    return JsonResponse({'reserva': _reserva_public(r)})


@csrf_exempt
def pagar_saldo(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    data = _body(request)
    r = _reserva_autorizada(data)
    if not r:
        return JsonResponse({'error': 'No encontramos una reserva con ese código y cédula'}, status=404)
    try:
        pago = services.crear_pago_saldo(r, str(data.get('nombrePagador') or '').strip())
    except services.ReservaError as e:
        return JsonResponse({'error': e.message}, status=e.status)
    return JsonResponse({'pago': services.pago_payload(pago)})


@csrf_exempt
def ya_transferi(request):
    """El cliente dio clic en 'Ya transferí': corre el plazo de VozPay."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    data = _body(request)
    r = _reserva_autorizada(data)
    if not r:
        return JsonResponse({'error': 'No encontramos una reserva con ese código y cédula'}, status=404)
    pago = Pago.objects.filter(reserva=r, transaction_id=str(data.get('transactionId') or '')).first()
    if not pago:
        return JsonResponse({'error': 'Pago no encontrado'}, status=404)
    result = services._vozpay('POST', f'/api/expectations/{pago.transaction_id}/confirm-transfer', {})
    if result is None:
        return JsonResponse({'error': 'No se pudo registrar la confirmación, intenta de nuevo'}, status=502)
    return JsonResponse({'ok': True, 'deadlineAt': result.get('deadline_at')})
