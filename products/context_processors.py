"""
Context processor que agrega KPIs reales al home del admin (dashboard),
para que la portada del panel muestre datos de negocio en vez de solo la
lista de modelos. Solo consulta la base de datos cuando la request es del
admin, para no pagar ese costo en el resto del sitio (API publica, etc).
"""
from django.db.models import Sum


def admin_kpis(request):
    path = getattr(request, 'path', '')
    if not path.startswith('/admin/'):
        return {}

    # Import diferido para evitar problemas de import circular en el arranque.
    from products.models import ProductAccounts, GameDetail, Coupon, CouponRedemption
    from rewards.models import JuegoPorVencer

    try:
        stock_total = GameDetail.objects.aggregate(total=Sum('stock'))['total'] or 0
        cuentas_activas = ProductAccounts.objects.filter(activa=True).count()
        cupones_activos = Coupon.objects.filter(is_valid=True).count()
        usos_cupon_total = CouponRedemption.objects.count()
    except Exception:
        # Si las tablas todavia no existen (primer deploy, migraciones
        # pendientes) no queremos romper el admin completo por esto.
        stock_total = cuentas_activas = cupones_activos = usos_cupon_total = None

    try:
        juegos_por_vencer_count = JuegoPorVencer.objects.count()
        proxima = JuegoPorVencer.objects.order_by('fecha_vencimiento').first()
        juegos_por_vencer_proxima = proxima.fecha_vencimiento if proxima else None
    except Exception:
        juegos_por_vencer_count = juegos_por_vencer_proxima = None

    return {
        'hc_kpis': {
            'stock_total': stock_total,
            'cuentas_activas': cuentas_activas,
            'cupones_activos': cupones_activos,
            'usos_cupon_total': usos_cupon_total,
            'juegos_por_vencer_count': juegos_por_vencer_count,
            'juegos_por_vencer_proxima': juegos_por_vencer_proxima,
        }
    }
