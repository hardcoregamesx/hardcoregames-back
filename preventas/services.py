"""Lógica de negocio de Preventas: fases, cupos, expiración y pagos por VozPay.

Los cobros usan el mismo pagos-nequi (VozPay) que ya confirma las
transferencias de la tienda: se registra una "expectativa" por
`transaction_id` y el webhook `transferenciaWebhook` (products/views.py)
avisa aquí cuando se confirma (`handle_event`). Los transaction_id de
preventas empiezan por `PV-`.
"""
import logging
from datetime import timedelta
import re
import secrets

from django.db import transaction as db_transaction
from django.utils import timezone

from .models import (
    ESTADO_CANCELADA, ESTADO_DESPACHADA, ESTADO_EXPIRADA, ESTADO_PAGADA, ESTADO_PENDIENTE,
    ESTADO_REEMBOLSADA, ESTADO_RESERVADA, FASE_PREVENTA, FASE_TARDIA, Pago, Preventa, Reserva,
)

logger = logging.getLogger(__name__)

TX_PREFIX = 'PV-'
RESERVA_MINUTOS = 60
CODIGO_ALFABETO = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # sin 0/O/1/I


# ----------------------------------------------------------------------- #
#  Fases y cupos                                                           #
# ----------------------------------------------------------------------- #

def fase_actual(preventa, now=None):
    now = now or timezone.now()
    if preventa.switch_at and now >= preventa.switch_at:
        return FASE_TARDIA
    return FASE_PREVENTA


def fase_info(preventa, fase=None):
    """Rango, precio final y disponibilidad de una fase."""
    fase = fase or fase_actual(preventa)
    if fase == FASE_TARDIA:
        disp = preventa.tardia_disponibles
        return {
            'fase': fase, 'min': preventa.tardia_min, 'max': preventa.tardia_max,
            'final': preventa.tardia_final, 'disponibles': disp,
            'agotado': disp is not None and disp <= 0,
        }
    return {
        'fase': fase, 'min': preventa.pre_min, 'max': preventa.pre_max,
        'final': preventa.pre_final, 'disponibles': None, 'agotado': False,
    }


def _tracked_stock(reserva):
    return reserva.fase == FASE_TARDIA


def _release_stock(reserva):
    """Devuelve las unidades al cupo de la tardía (solo si tiene tope)."""
    if not _tracked_stock(reserva):
        return
    p = Preventa.objects.select_for_update().get(pk=reserva.preventa_id)
    if p.tardia_disponibles is not None:
        p.tardia_disponibles += reserva.unidades
        p.save(update_fields=['tardia_disponibles'])


def _take_stock(reserva):
    if not _tracked_stock(reserva):
        return
    p = Preventa.objects.select_for_update().get(pk=reserva.preventa_id)
    if p.tardia_disponibles is not None:
        p.tardia_disponibles -= reserva.unidades
        p.save(update_fields=['tardia_disponibles'])


# ----------------------------------------------------------------------- #
#  Saldo                                                                   #
# ----------------------------------------------------------------------- #

def abonado_total(reserva):
    """Reserva pagada + abonos/saldo confirmados. El envío NO entra."""
    total = reserva.reserva_total if reserva.paid_at else 0
    for pago in reserva.pagos.filter(status='approved', tipo__in=('ABONO', 'SALDO')):
        total += pago.monto
    return total


def saldo_info(reserva):
    """Saldo pendiente de una reserva. El envío NO entra: se paga al recibir.

    Tope de abonos: el precio final × unidades si ya se fijó; si no, el
    precio máximo estimado de la fase de la reserva × unidades."""
    p = reserva.preventa
    info = fase_info(p, reserva.fase)
    unidades = reserva.unidades
    abonado = abonado_total(reserva)
    extra = {'abonado': abonado, 'permite_abonos': bool(p.permitir_abonos), 'abono_minimo': p.abono_minimo}
    if info['final'] is not None:
        total = info['final'] * unidades
        saldo = max(total - abonado, 0)
        return {**extra, 'definitivo': True, 'precio_unit': info['final'], 'saldo': saldo,
                'saldo_min': saldo, 'saldo_max': saldo, 'tope': total, 'max_abono': saldo}
    tope = info['max'] * unidades
    return {
        **extra, 'definitivo': False, 'precio_unit': None, 'saldo': None,
        'saldo_min': max(info['min'] * unidades - abonado, 0),
        'saldo_max': max(tope - abonado, 0), 'tope': tope, 'max_abono': max(tope - abonado, 0),
    }


def sync_estado(reserva):
    """Si ya se fijó el precio final y lo abonado lo cubre, pasa a PAGADA.
    Se llama al confirmarse un pago y al consultar (el admin pudo fijar el
    precio después de que el cliente abonara)."""
    if reserva.estado != ESTADO_RESERVADA:
        return
    s = saldo_info(reserva)
    if s['definitivo'] and s['saldo'] <= 0:
        reserva.estado = ESTADO_PAGADA
        reserva.saldo_paid_at = timezone.now()
        reserva.save(update_fields=['estado', 'saldo_paid_at'])


# ----------------------------------------------------------------------- #
#  pagos-nequi (VozPay)                                                    #
# ----------------------------------------------------------------------- #

def _vozpay(method, path, body):
    from products import views  # import tardío: evita ciclo con el webhook
    return views._pagos_nequi_call(method, path, body)


def _breb_key(preventa):
    from products import views
    return (preventa.breb_key or '').strip() or views._get_breb_key()


def _nuevo_pago(reserva, tipo, monto, nombre_pagador):
    """Crea el Pago y registra la expectativa en VozPay. None si VozPay falla."""
    tx_id = f'{TX_PREFIX}{secrets.token_hex(6).upper()}'
    breb = _breb_key(reserva.preventa)
    registered = _vozpay('POST', '/api/expectations', {
        'transaction_id': tx_id, 'nombre_pagador': nombre_pagador, 'monto_cop': monto,
    })
    if registered is None:
        return None
    return Pago.objects.create(
        transaction_id=tx_id, reserva=reserva, tipo=tipo, monto=monto, status='pendiente',
        nombre_pagador=nombre_pagador, breb_key=breb,
        deadline_at=str(registered.get('deadline_at') or ''),
    )


def pago_payload(pago):
    return {
        'transactionId': pago.transaction_id, 'tipo': pago.tipo, 'monto': pago.monto,
        'breBKey': pago.breb_key, 'deadlineAt': pago.deadline_at or None,
    }


# ----------------------------------------------------------------------- #
#  Crear reserva                                                           #
# ----------------------------------------------------------------------- #

class ReservaError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _codigo_unico():
    for _ in range(20):
        code = 'HC-' + ''.join(secrets.choice(CODIGO_ALFABETO) for _ in range(6))
        if not Reserva.objects.filter(codigo=code).exists():
            return code
    raise ReservaError('No se pudo generar el código, intenta de nuevo', 500)


def expirar_vencidas():
    """Expira reservas sin pagar cuyo plazo venció y libera su cupo."""
    ahora = timezone.now()
    ids = list(Reserva.objects.filter(estado=ESTADO_PENDIENTE, expires_at__lt=ahora).values_list('id', flat=True)[:50])
    for rid in ids:
        _expirar(rid, cancelar_en_vozpay=True)


def _expirar(reserva_id, cancelar_en_vozpay):
    pendientes = []
    with db_transaction.atomic():
        r = Reserva.objects.select_for_update().get(pk=reserva_id)
        if r.estado != ESTADO_PENDIENTE:
            return
        r.estado = ESTADO_EXPIRADA
        r.save(update_fields=['estado'])
        _release_stock(r)
        for pago in r.pagos.filter(status='pendiente'):
            pago.status = 'cancelada'
            pago.save(update_fields=['status'])
            pendientes.append(pago.transaction_id)
    if cancelar_en_vozpay:
        for tx in pendientes:
            _vozpay('POST', f'/api/expectations/{tx}/cancel', {})


def crear_reserva(preventa, datos):
    """`datos` ya validado. Devuelve (reserva, pago)."""
    unidades = datos['unidades']
    with db_transaction.atomic():
        p = Preventa.objects.select_for_update().get(pk=preventa.pk)
        if not p.active:
            raise ReservaError('Esta preventa no está activa', 409)
        fase = fase_actual(p)
        info = fase_info(p, fase)
        if info['agotado']:
            raise ReservaError('Agotado', 409)
        if fase == FASE_TARDIA and p.tardia_disponibles is not None:
            if unidades > p.tardia_disponibles:
                raise ReservaError(f'Solo quedan {p.tardia_disponibles} unidades disponibles', 409)
            p.tardia_disponibles -= unidades
            p.save(update_fields=['tardia_disponibles'])
        reserva = Reserva.objects.create(
            codigo=_codigo_unico(), preventa=p, fase=fase, unidades=unidades,
            nombre=datos['nombre'], whatsapp=datos['whatsapp'], direccion=datos['direccion'],
            ciudad=datos['ciudad'], cedula=datos['cedula'], fuente=datos['fuente'],
            envio_tipo=datos['envio_tipo'], ciudad_intermedia=datos['ciudad_intermedia'],
            reserva_total=p.reserva_unit * unidades, estado=ESTADO_PENDIENTE,
            expires_at=timezone.now() + timedelta(minutes=RESERVA_MINUTOS),
        )
    pago = _nuevo_pago(reserva, 'RESERVA', reserva.reserva_total, datos['nombre_pagador'])
    if pago is None:
        with db_transaction.atomic():
            r = Reserva.objects.select_for_update().get(pk=reserva.pk)
            r.estado = ESTADO_CANCELADA
            r.save(update_fields=['estado'])
            _release_stock(r)
        raise ReservaError('No se pudo iniciar la verificación del pago, intenta de nuevo', 502)
    return reserva, pago


def crear_pago_saldo(reserva, nombre_pagador):
    """Genera (o reutiliza) el cobro del saldo. Devuelve el Pago o lanza ReservaError."""
    if reserva.estado != ESTADO_RESERVADA:
        raise ReservaError('Esta reserva no tiene saldo por pagar', 409)
    s = saldo_info(reserva)
    if not s['definitivo']:
        raise ReservaError('El precio final aún no está definido', 409)
    if s['saldo'] <= 0:
        raise ReservaError('No hay saldo pendiente', 409)
    reutilizable = _cancelar_pendientes(reserva, tipo='SALDO', monto=s['saldo'])
    if reutilizable:
        return reutilizable
    pago = _nuevo_pago(reserva, 'SALDO', s['saldo'], nombre_pagador or reserva.nombre)
    if pago is None:
        raise ReservaError('No se pudo iniciar la verificación del pago, intenta de nuevo', 502)
    return pago


def _cancelar_pendientes(reserva, tipo=None, monto=None):
    """Cancela los cobros pendientes de la reserva (solo uno puede estar
    abierto a la vez). Si hay uno idéntico (mismo tipo y monto) lo devuelve
    sin cancelarlo, para reutilizarlo."""
    for pago in reserva.pagos.filter(status='pendiente').exclude(tipo='RESERVA'):
        if tipo and pago.tipo == tipo and pago.monto == monto:
            return pago
        pago.status = 'cancelada'
        pago.save(update_fields=['status'])
        _vozpay('POST', f'/api/expectations/{pago.transaction_id}/cancel', {})
    return None


def crear_pago_abono(reserva, monto, nombre_pagador):
    """Abono libre: mínimo `abono_minimo` y hasta el tope de la fase."""
    p = reserva.preventa
    if not p.permitir_abonos:
        raise ReservaError('Esta preventa no permite abonos', 409)
    if reserva.estado != ESTADO_RESERVADA:
        raise ReservaError('Esta reserva no puede recibir abonos', 409)
    s = saldo_info(reserva)
    if s['max_abono'] <= 0:
        raise ReservaError('Ya alcanzaste el tope de abonos', 409)
    try:
        monto = int(monto)
    except (TypeError, ValueError):
        raise ReservaError('Escribe un valor válido')
    if monto > s['max_abono']:
        raise ReservaError(f"Puedes abonar máximo ${s['max_abono']:,}".replace(',', '.'))
    if monto < p.abono_minimo and monto != s['max_abono']:
        raise ReservaError(f'El abono mínimo es ${p.abono_minimo:,}'.replace(',', '.'))
    reutilizable = _cancelar_pendientes(reserva, tipo='ABONO', monto=monto)
    if reutilizable:
        return reutilizable
    pago = _nuevo_pago(reserva, 'ABONO', monto, nombre_pagador or reserva.nombre)
    if pago is None:
        raise ReservaError('No se pudo iniciar la verificación del pago, intenta de nuevo', 502)
    return pago


# ----------------------------------------------------------------------- #
#  Webhook de VozPay                                                       #
# ----------------------------------------------------------------------- #

def handle_event(data):
    """Procesa un evento de pagos-nequi. True si era de preventas (se maneja
    aquí y el webhook general no debe seguir)."""
    tx = data.get('transaction_id') or ''
    if not tx.startswith(TX_PREFIX):
        return False
    confidence = data.get('confidence')
    try:
        with db_transaction.atomic():
            pago = Pago.objects.select_for_update().filter(transaction_id=tx).first()
            if not pago:
                logger.warning('preventas: evento para pago desconocido %s', tx)
                return True
            if confidence == 'alta':
                _aprobar(pago)
            elif confidence == 'vencida':
                _vencer(pago)
            else:
                logger.warning('preventas: confidence desconocida %r para %s', confidence, tx)
    except Exception:
        logger.exception('preventas: error procesando evento %s', tx)
    return True


def _aprobar(pago):
    if pago.status == 'approved':
        return
    pago.status = 'approved'
    pago.save(update_fields=['status'])
    r = Reserva.objects.select_for_update().get(pk=pago.reserva_id)
    ahora = timezone.now()
    if pago.tipo == 'RESERVA':
        if r.estado == ESTADO_PENDIENTE:
            r.estado = ESTADO_RESERVADA
            r.paid_at = ahora
            r.save(update_fields=['estado', 'paid_at'])
        elif r.estado in (ESTADO_EXPIRADA, ESTADO_CANCELADA):
            # Pagó tarde: el dinero ya entró, se respeta la reserva y se vuelve
            # a descontar el cupo (puede quedar negativo; el admin lo ve).
            logger.warning('preventas: pago tardío de %s, se reactiva la reserva', r.codigo)
            r.estado = ESTADO_RESERVADA
            r.paid_at = ahora
            r.save(update_fields=['estado', 'paid_at'])
            _take_stock(r)
    elif pago.tipo in ('SALDO', 'ABONO'):
        # El pago ya quedó 'approved' arriba, así que abonado_total() lo cuenta.
        sync_estado(r)


def _vencer(pago):
    if pago.status != 'pendiente':
        return
    pago.status = 'cancelada'
    pago.save(update_fields=['status'])
    if pago.tipo == 'RESERVA':
        r = Reserva.objects.select_for_update().get(pk=pago.reserva_id)
        if r.estado == ESTADO_PENDIENTE:
            r.estado = ESTADO_EXPIRADA
            r.save(update_fields=['estado'])
            _release_stock(r)


# ----------------------------------------------------------------------- #
#  Acciones del admin                                                      #
# ----------------------------------------------------------------------- #

def cerrar_reserva(reserva_id, nuevo_estado):
    """Cancela/reembolsa a mano y devuelve el cupo si seguía ocupándolo."""
    assert nuevo_estado in (ESTADO_CANCELADA, ESTADO_REEMBOLSADA)
    with db_transaction.atomic():
        r = Reserva.objects.select_for_update().get(pk=reserva_id)
        if r.estado in (ESTADO_CANCELADA, ESTADO_REEMBOLSADA, ESTADO_EXPIRADA):
            if r.estado != nuevo_estado and r.estado != ESTADO_EXPIRADA:
                r.estado = nuevo_estado
                r.save(update_fields=['estado'])
            return
        ocupaba_cupo = r.estado in (ESTADO_PENDIENTE, ESTADO_RESERVADA, ESTADO_PAGADA, ESTADO_DESPACHADA)
        r.estado = nuevo_estado
        r.save(update_fields=['estado'])
        if ocupaba_cupo:
            _release_stock(r)


# ----------------------------------------------------------------------- #
#  Validación y presentación                                               #
# ----------------------------------------------------------------------- #

def solo_digitos(valor):
    return re.sub(r'\D', '', str(valor or ''))


def mask_cedula(cedula):
    c = str(cedula or '')
    return ('•' * max(len(c) - 3, 0)) + c[-3:]
