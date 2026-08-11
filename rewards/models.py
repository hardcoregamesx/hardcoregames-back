from django.contrib.auth.models import User
from django.db import models

from products.models import Coupon


# ----------------------------------------------------------------------- #
#  Todas las tablas de este modulo son gestionadas por hc-fastapi          #
#  (SQLAlchemy Base.metadata.create_all en app/models.py). Django solo     #
#  las administra via el panel: managed = False evita que makemigrations/  #
#  migrate intente crearlas, alterarlas o borrarlas. Mismo patron que      #
#  products.models.ProductAlias.                                          #
# ----------------------------------------------------------------------- #

POINT_TRANSACTION_REASONS = [
    ('PURCHASE', 'Compra'),
    ('ROULETTE_SPIN', 'Giro de ruleta'),
    ('COUPON', 'Cupón'),
    ('EXCHANGE', 'Canje por saldo'),
    ('ADMIN_ADJUST', 'Ajuste administrativo'),
    ('REFUND', 'Devolución'),
]

PRIZE_TYPES = [
    ('COUPON_FIXED', 'Cupón de valor fijo'),
    ('COUPON_PERCENT', 'Cupón de porcentaje'),
    ('POINTS', 'Puntos'),
    ('NOTHING', 'Nada'),
]


class PointTransaction(models.Model):
    """Ledger de movimientos de puntos. Fuente de verdad para auditar el
    saldo de cualquier usuario en cualquier momento."""

    user = models.ForeignKey(User, on_delete=models.DO_NOTHING, db_column='user_id', related_name='point_transactions')
    delta = models.IntegerField()
    balance_after = models.IntegerField()
    reason = models.CharField(max_length=30, choices=POINT_TRANSACTION_REASONS)
    reference_type = models.CharField(max_length=50, null=True, blank=True)
    reference_id = models.CharField(max_length=100, null=True, blank=True)
    description = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'rewards_pointtransaction'
        verbose_name = 'movimiento de puntos'
        verbose_name_plural = 'Ledger de puntos'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} {self.delta:+d} ({self.reason})'


class Roulette(models.Model):
    """Una rueda configurable. En la practica solo una activa a la vez."""

    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    cost_points = models.IntegerField(default=0)
    max_spins_per_day = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'rewards_roulette'
        verbose_name = 'ruleta'
        verbose_name_plural = 'Ruletas'

    def __str__(self):
        return self.name


class RoulettePrize(models.Model):
    """Premio configurable de una rueda. `weight` es la probabilidad
    relativa y nunca se expone al cliente via la API publica."""

    roulette = models.ForeignKey(Roulette, on_delete=models.DO_NOTHING, db_column='roulette_id', related_name='prizes')
    name = models.CharField(max_length=100)
    prize_type = models.CharField(max_length=20, choices=PRIZE_TYPES)
    value = models.IntegerField(default=0, help_text='Monto fijo, % de descuento, o puntos, según prize_type.')
    weight = models.IntegerField(default=1, help_text='Peso relativo para la selección ponderada (no es un %).')
    coupon_validity_minutes = models.IntegerField(null=True, blank=True, help_text='Minutos de vigencia del cupón generado. Vacío = 60 min por defecto.')
    min_purchase = models.IntegerField(null=True, blank=True)
    max_per_user = models.IntegerField(null=True, blank=True)
    stock = models.IntegerField(null=True, blank=True, help_text='Vacío = stock ilimitado.')
    color = models.CharField(max_length=20, default='#7c3aed')
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'rewards_rouletteprize'
        verbose_name = 'premio de ruleta'
        verbose_name_plural = 'Premios de ruleta'
        ordering = ['roulette', 'display_order']

    def __str__(self):
        return f'{self.name} ({self.roulette})'


class RouletteSpin(models.Model):
    """Auditoria de cada giro: quien, cuando, que le toco y que cupon generó."""

    user = models.ForeignKey(User, on_delete=models.DO_NOTHING, db_column='user_id', related_name='roulette_spins')
    roulette = models.ForeignKey(Roulette, on_delete=models.DO_NOTHING, db_column='roulette_id', related_name='spins')
    prize = models.ForeignKey(RoulettePrize, on_delete=models.DO_NOTHING, db_column='prize_id', related_name='spins')
    points_spent = models.IntegerField(default=0)
    coupon = models.ForeignKey(Coupon, on_delete=models.DO_NOTHING, db_column='coupon_id', null=True, blank=True, related_name='roulette_spin')
    idempotency_key = models.CharField(max_length=100)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'rewards_roulettespin'
        verbose_name = 'giro de ruleta'
        verbose_name_plural = 'Giros de ruleta'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} → {self.prize} ({self.created_at:%Y-%m-%d %H:%M})'
