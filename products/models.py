from datetime import datetime

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


# Create your models here.
class ProductsType(models.Model):
    id_product_type = models.AutoField(primary_key=True)
    description = models.CharField(max_length=200)

    def __str__(self):
        return self.description

    class Meta:
        verbose_name = 'un tipo de producto'
        verbose_name_plural = 'Tipos de producto'


class Consoles(models.Model):
    id_console = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)
    estado = models.BooleanField(null=True)

    def __str__(self):
        return self.descripcion

    def get_id_console(self):
        return self.id_console

    class Meta:
        verbose_name = 'una consola'
        verbose_name_plural = 'Consolas'


class TypeGames(models.Model):
    id_type_game = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    def __str__(self):
        return self.descripcion

    class Meta:
        verbose_name = 'una tipo de juego'
        verbose_name_plural = 'Tipos de juegos'


class Products(models.Model):
    id_product = models.AutoField(primary_key=True)
    title = models.CharField(max_length=200, default="")
    description = models.TextField()
    date_register = models.DateField(default=datetime.now)
    date_last_modified = models.DateField(auto_now=True)
    image = models.CharField(max_length=500)
    type_id = models.ForeignKey(ProductsType, on_delete=models.CASCADE)
    calification = models.IntegerField(default=0)
    consola = models.ManyToManyField(Consoles)
    tipo_juego = models.ForeignKey(TypeGames, on_delete=models.CASCADE, null=True, blank=True)
    puntos_venta = models.IntegerField(default=0)
    puede_rentarse = models.BooleanField(default=True)
    destacado = models.BooleanField(default=False)

    def __str__(self):
        return str(self.id_product) + " " + str(self.title)

    class Meta:
        verbose_name = 'un producto'
        verbose_name_plural = 'Productos'


class TypeAccounts(models.Model):
    id_type_account = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    def __str__(self):
        return self.descripcion

    class Meta:
        verbose_name = 'Tipo cuenta'
        verbose_name_plural = 'Tipos de cuentas'


class TypeSuscriptionAccounts(models.Model):
    id_type_suscription_account = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    def __str__(self):
        return self.descripcion

    class Meta:
        verbose_name = 'Tipo cuenta suscripcion'
        verbose_name_plural = 'Tipos de cuentas suscripcion'


class ProductAccounts(models.Model):
    id_product_accounts = models.AutoField(primary_key=True)
    cuenta = models.CharField(max_length=200)
    password = models.CharField(max_length=100, null=True, blank=True)
    activa = models.BooleanField()
    tipo_cuenta = models.ForeignKey(TypeAccounts, on_delete=models.CASCADE, default=1)
    dias_duracion = models.IntegerField(default=0, null=True, blank=True)
    codigo_seguridad = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        verbose_name = 'una cuenta para producto'
        verbose_name_plural = 'Cuentas para productos'

    def __str__(self):
        return self.cuenta


class Licenses(models.Model):
    id_license = models.AutoField(primary_key=True)
    descripcion = models.CharField(max_length=100)

    def __str__(self):
        return self.descripcion

    def get_id_licence(self):
        return self.id_license

    class Meta:
        verbose_name = 'Licencia'
        verbose_name_plural = 'Licencias'


class GameDetail(models.Model):
    id_game_detail = models.AutoField(primary_key=True)
    producto = models.ForeignKey(Products, on_delete=models.CASCADE, null=True)
    consola = models.ForeignKey(Consoles, on_delete=models.CASCADE, null=True)
    licencia = models.ForeignKey(Licenses, on_delete=models.CASCADE, null=True)
    cuenta = models.ForeignKey(ProductAccounts, on_delete=models.CASCADE, null=True)
    duracion_dias_alquiler = models.IntegerField(null=True)
    stock = models.IntegerField()
    precio = models.IntegerField(default=0)
    precio_descuento = models.IntegerField(default=0)

    class Meta:
        verbose_name = 'Precio por consola y licencia'
        verbose_name_plural = 'Precios por consola y licencia'

    def __str__(self):
        product_name = self.producto.title if self.producto else 'Sin producto'
        return f"{product_name} | {self.licencia} | {self.consola} | {self.duracion_dias_alquiler}"


class SaleDetail(models.Model):
    id_sale_detail = models.AutoField(primary_key=True)
    fecha_venta = models.DateTimeField(default=datetime.now, blank=True)
    fecha_vencimiento = models.DateField(null=True)
    cuenta = models.ForeignKey(ProductAccounts, on_delete=models.CASCADE, null=True)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    producto = models.ForeignKey(Products, on_delete=models.CASCADE, null=True)
    combinacion = models.ForeignKey(GameDetail, on_delete=models.CASCADE, null=True)

    class Meta:
        verbose_name = 'un detalle de venta'
        verbose_name_plural = 'Detalle de ventas'

    def __str__(self):
        return "Detalle de venta para la cuenta " + self.cuenta.cuenta


class ShoppingCar(models.Model):
    id_shopping_car = models.AutoField(primary_key=True)
    producto = models.ForeignKey(GameDetail, on_delete=models.CASCADE)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    estado = models.BooleanField()

    # def __str__(self):
    #     return "Detalle de venta para la cuenta " + self.cuenta.cuenta


class Files(models.Model):
    id_file = models.AutoField(primary_key=True)
    archivo = models.FileField(upload_to=settings.STATIC_URL_FILES)
    estado = models.BooleanField(default=True)
    procesado = models.BooleanField(default=False, verbose_name='Procesado')
    resultado = models.TextField(blank=True, null=True, verbose_name='Resultado del procesamiento')

    class Meta:
        verbose_name = 'un archivo para precios'
        verbose_name_plural = 'Archivos para precios'


class DaysForRentail(models.Model):
    id_day = models.AutoField(primary_key=True)
    numero_dias = models.CharField(max_length=100)
    porcentaje_descuento = models.CharField(max_length=100)

    def __str__(self):
        return self.numero_dias

    class Meta:
        verbose_name = 'valor descuento por mes'
        verbose_name_plural = 'Meses para alquiler'


class PriceForSuscription(models.Model):
    id_price_suscription = models.AutoField(primary_key=True)
    producto = models.ForeignKey(Products, on_delete=models.CASCADE, null=True)
    tipo_producto = models.ForeignKey(TypeSuscriptionAccounts, on_delete=models.CASCADE)
    tiempo_alquiler = models.CharField(max_length=100, default="")
    stock = models.IntegerField(default=0)
    duracion_dias_alquiler = models.IntegerField(default=0)
    precio = models.IntegerField()
    estado = models.BooleanField(default=True)

    def __str__(self):
        return str(self.producto.id_product) + " " + str(self.producto.title)

    class Meta:
        verbose_name = 'precio producto suscripción'
        verbose_name_plural = 'Precio producto suscripción'


class VariablesSistema(models.Model):
    id_vairables_sistema = models.AutoField(primary_key=True)
    nombre_variable = models.CharField(max_length=100)
    descripcion = models.TextField(null=True, default=None, blank=True)
    valor = models.TextField()
    url = models.TextField(null=True, default=None, blank=True)
    estado = models.BooleanField(default=True)

    def __str__(self):
        return str(self.nombre_variable)

    class Meta:
        verbose_name = 'variable de sistema'
        verbose_name_plural = 'Variables de sistema'

class Transactions(models.Model):
    id_transaction = models.AutoField(primary_key=True)
    date_transaction = models.DateTimeField(default=datetime.now, blank=True)
    status = models.CharField(max_length=100)
    amount = models.IntegerField()
    payment_id = models.CharField(max_length=100)
    ref_payco = models.CharField(max_length=100)
    request = models.TextField(blank=True, null=True)
    id_invoice = models.CharField(max_length=100)
    user_id = models.ForeignKey(User, on_delete=models.CASCADE)


class Coupon(models.Model):
    DISCOUNT_TYPE_CHOICES = [
        ('PERCENTAGE', 'Porcentaje'),
        ('FIXED_AMOUNT', 'Monto fijo (bono)'),
    ]
    SOURCE_CHOICES = [
        ('MANUAL', 'Manual'),
        ('WELCOME', 'Bienvenida'),
        ('ROULETTE', 'Ruleta'),
        ('MISSION', 'Misión'),
        ('LOYALTY', 'Fidelización'),
        ('CAMPAIGN', 'Campaña'),
        ('ADMIN', 'Administración'),
        ('REFERRAL', 'Referido'),
    ]

    id_coupon = models.AutoField(primary_key=True)
    name_coupon = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    expiration_date = models.DateTimeField()
    is_valid = models.BooleanField(default=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    game_details = models.ManyToManyField('GameDetail', blank=True, related_name='coupons')
    percentage_off = models.IntegerField(default=0)
    points_given = models.IntegerField(default=0)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPE_CHOICES, default='PERCENTAGE')
    fixed_amount = models.IntegerField(default=0, help_text='Monto en COP cuando discount_type = FIXED_AMOUNT.')
    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, default='MANUAL')

    class Meta:
        db_table = 'coupons_coupon'
        verbose_name = 'cupón'
        verbose_name_plural = 'cupones'

    def __str__(self):
        return self.name_coupon

    # ------------------------------------------------------------------ #
    #  Rule evaluation                                                     #
    # ------------------------------------------------------------------ #
    def validate_coupon(self, user, cart_total, cart_items, payment_method=None):
        """
        Evaluate all CouponRule objects linked to this coupon.

        Parameters
        ----------
        user            : django.contrib.auth.models.User
        cart_total      : numeric  – total monetary value of the cart
        cart_items      : list[dict] – each dict may have keys:
                          'product_id', 'category_id', 'quantity'
        payment_method  : str | None

        Returns
        -------
        (is_valid: bool, reason: str)
        """
        if not self.is_valid:
            return False, 'El cupón no está activo.'

        if timezone.now() > self.expiration_date:
            return False, 'El cupón ha expirado.'

        if self.user_id and self.user_id != user.pk:
            return False, 'Este cupón no es válido para tu cuenta.'

        coupon_game_detail_ids = list(self.game_details.values_list('id_game_detail', flat=True))
        if coupon_game_detail_ids:
            cart_combination_ids = [item.get('id_combination') for item in cart_items]
            if not any(gd_id in cart_combination_ids for gd_id in coupon_game_detail_ids):
                return False, 'El cupón no aplica a los productos del carrito.'

        for rule in self.rules.select_related():
            valid, reason = rule.evaluate(user, cart_total, cart_items)
            if not valid:
                return False, reason

        return True, 'Cupón válido.'


# ------------------------------------------------------------------ #
#  CouponRule                                                          #
# ------------------------------------------------------------------ #

class CouponRule(models.Model):
    class RuleType(models.TextChoices):
        MIN_ORDER_AMOUNT   = 'min_order_amount',   'Monto mínimo de orden'
        MAX_ORDER_AMOUNT   = 'max_order_amount',   'Monto máximo de orden'
        MIN_ITEM_QUANTITY  = 'min_item_quantity',  'Cantidad mínima de ítems'
        ALLOWED_CATEGORIES = 'allowed_categories', 'Categorías permitidas'
        FIRST_PURCHASE_ONLY = 'first_purchase_only', 'Solo primera compra'
        USAGE_LIMIT_TOTAL  = 'usage_limit_total',  'Límite de usos totales'
        USAGE_LIMIT_PER_USER = 'usage_limit_per_user', 'Límite de usos por usuario'
        DAY_OF_WEEK        = 'day_of_week',        'Día de la semana'

    class Operator(models.TextChoices):
        GTE     = 'gte',     'Mayor o igual (>=)'
        LTE     = 'lte',     'Menor o igual (<=)'
        EQ      = 'eq',      'Igual (=)'
        IN      = 'in',      'En lista (in)'
        BETWEEN = 'between', 'Entre (between)'

    coupon = models.ForeignKey(
        Coupon, on_delete=models.CASCADE, related_name='rules'
    )
    rule_type = models.CharField(
        max_length=50, choices=RuleType.choices, verbose_name='Tipo de regla'
    )
    operator = models.CharField(
        max_length=10, choices=Operator.choices, verbose_name='Operador'
    )
    value = models.JSONField(
        verbose_name='Valor',
        help_text=(
            'JSON con la configuración de la regla. Ejemplos: '
            '{"amount": 50000} | {"quantity": 3} | {"categories": [1,2]} | '
            '{"limit": 5} | {"days": [0,1,2,3,4]} | {"min": 10000, "max": 200000}'
        ),
    )

    class Meta:
        verbose_name = 'regla de cupón'
        verbose_name_plural = 'reglas de cupón'

    def __str__(self):
        return f'{self.get_rule_type_display()} [{self.get_operator_display()}]'

    def evaluate(self, user, cart_total, cart_items):
        """
        Evaluate this single rule.

        Returns
        -------
        (is_valid: bool, reason: str)
        """
        rt = self.rule_type
        op = self.operator
        v  = self.value or {}

        # --- min_order_amount -------------------------------------------
        if rt == self.RuleType.MIN_ORDER_AMOUNT:
            amount = v.get('amount', 0)
            if op == self.Operator.GTE:
                if cart_total >= amount:
                    return True, ''
                return False, f'El monto mínimo de la orden debe ser {amount}.'
            if op == self.Operator.BETWEEN:
                min_val = v.get('min', 0)
                max_val = v.get('max', float('inf'))
                if min_val <= cart_total <= max_val:
                    return True, ''
                return False, f'El monto de la orden debe estar entre {min_val} y {max_val}.'

        # --- max_order_amount -------------------------------------------
        elif rt == self.RuleType.MAX_ORDER_AMOUNT:
            amount = v.get('amount', float('inf'))
            if op == self.Operator.LTE:
                if cart_total <= amount:
                    return True, ''
                return False, f'El monto máximo de la orden es {amount}.'
            if op == self.Operator.BETWEEN:
                min_val = v.get('min', 0)
                max_val = v.get('max', float('inf'))
                if min_val <= cart_total <= max_val:
                    return True, ''
                return False, f'El monto de la orden debe estar entre {min_val} y {max_val}.'

        # --- min_item_quantity ------------------------------------------
        elif rt == self.RuleType.MIN_ITEM_QUANTITY:
            min_qty   = v.get('quantity', 0)
            total_qty = sum(item.get('quantity', 1) for item in cart_items)
            if op == self.Operator.GTE:
                if total_qty >= min_qty:
                    return True, ''
                return False, f'Se requieren al menos {min_qty} ítems en el carrito.'
            if op == self.Operator.EQ:
                if total_qty == min_qty:
                    return True, ''
                return False, f'Se requieren exactamente {min_qty} ítems en el carrito.'
            if op == self.Operator.BETWEEN:
                max_qty = v.get('max', float('inf'))
                if min_qty <= total_qty <= max_qty:
                    return True, ''
                return False, f'La cantidad de ítems debe estar entre {min_qty} y {max_qty}.'

        # --- allowed_categories -----------------------------------------
        elif rt == self.RuleType.ALLOWED_CATEGORIES:
            allowed        = v.get('categories', [])
            cart_categories = {item.get('category_id') for item in cart_items}
            if op == self.Operator.IN:
                if cart_categories & set(allowed):
                    return True, ''
                return False, 'Ningún ítem del carrito pertenece a las categorías permitidas.'

        # --- first_purchase_only ----------------------------------------
        elif rt == self.RuleType.FIRST_PURCHASE_ONLY:
            has_purchases = SaleDetail.objects.filter(usuario=user).exists()
            if not has_purchases:
                return True, ''
            return False, 'Este cupón es válido solo para la primera compra.'

        # --- usage_limit_total ------------------------------------------
        elif rt == self.RuleType.USAGE_LIMIT_TOTAL:
            limit      = v.get('limit', 0)
            total_used = CouponRedemption.objects.filter(coupon=self.coupon).count()
            if op in (self.Operator.LTE, self.Operator.EQ):
                if total_used < limit:
                    return True, ''
            return False, 'El cupón ha alcanzado el límite máximo de usos.'

        # --- usage_limit_per_user ---------------------------------------
        elif rt == self.RuleType.USAGE_LIMIT_PER_USER:
            limit    = v.get('limit', 1)
            user_used = CouponRedemption.objects.filter(
                coupon=self.coupon, user=user
            ).count()
            if op in (self.Operator.LTE, self.Operator.EQ):
                if user_used < limit:
                    return True, ''
            return False, 'Has alcanzado el límite de usos de este cupón.'

        # --- day_of_week ------------------------------------------------
        elif rt == self.RuleType.DAY_OF_WEEK:
            allowed_days = v.get('days', [])  # 0=Monday … 6=Sunday
            current_day  = timezone.now().weekday()
            if op == self.Operator.IN:
                if current_day in allowed_days:
                    return True, ''
                day_names    = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
                allowed_names = ', '.join(day_names[d] for d in allowed_days if 0 <= d <= 6)
                return False, f'El cupón solo es válido los siguientes días: {allowed_names}.'

        # Fallback – unknown / unhandled combination passes silently
        return True, ''


# ------------------------------------------------------------------ #
#  CouponRedemption                                                    #
# ------------------------------------------------------------------ #

class CouponRedemption(models.Model):
    coupon = models.ForeignKey(
        Coupon, on_delete=models.CASCADE, related_name='redemptions', verbose_name='Cupón'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='coupon_redemptions',
        verbose_name='Usuario',
    )
    order_id    = models.CharField(max_length=100, verbose_name='ID de orden')
    redeemed_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de uso')

    class Meta:
        verbose_name        = 'uso de cupón'
        verbose_name_plural = 'usos de cupón'
        ordering            = ['-redeemed_at']
        indexes             = [models.Index(fields=['coupon', 'user'])]

    def __str__(self):
        return f'{self.coupon.name_coupon} – {self.user.username} – {self.order_id}'


# ------------------------------------------------------------------ #
#  CouponPurgeLog                                                      #
# ------------------------------------------------------------------ #

class CouponPurgeLog(models.Model):
    """Contador agregado de cupones vencidos-sin-usar que fueron purgados.

    Una fila por (source, period), nunca una fila por cupón: así el conteo
    histórico de "generados vs usados" no se pierde al purgar, sin que esta
    tabla crezca con el volumen de cupones. Tabla creada a mano vía SQL
    directo (managed = False), no vía migrate — igual que ProductAlias, ver
    nota en products/models.py sobre esta app sin migraciones.
    """

    source = models.CharField(max_length=30, choices=Coupon.SOURCE_CHOICES)
    period = models.CharField(max_length=7, help_text='Mes en formato YYYY-MM, según created_at del cupón purgado.')
    count = models.IntegerField(default=0)

    class Meta:
        managed = False
        db_table = 'products_couponpurgelog'
        verbose_name = 'purga de cupones'
        verbose_name_plural = 'Purgas de cupones (histórico agregado)'
        unique_together = [('source', 'period')]
        ordering = ['-period', 'source']

    def __str__(self):
        return f'{self.source} {self.period}: {self.count}'


# ------------------------------------------------------------------ #
#  Proxy model – Productos Destacados                                  #
# ------------------------------------------------------------------ #

class ProductoDestacado(Products):
    """Proxy model used exclusively by the Productos Destacados admin page."""

    class Meta:
        proxy = True
        verbose_name = 'Producto Destacado'
        verbose_name_plural = 'Productos Destacados'


# ------------------------------------------------------------------ #
#  Proxy model – Inventario de GameDetail                              #
# ------------------------------------------------------------------ #

class GameDetailInventario(GameDetail):
    """Proxy model for the Inventario de Productos admin page."""

    class Meta:
        proxy = True
        verbose_name = 'Inventario de Producto'
        verbose_name_plural = 'Inventario de Productos'


# ------------------------------------------------------------------ #
#  Alias de producto (para busqueda por nombres alternativos)        #
# ------------------------------------------------------------------ #

class ProductAlias(models.Model):
    """Apunta a la tabla products_productalias, que ya existe y es usada
    por el servicio hc-fastapi (SQLAlchemy) para busqueda por alias en la
    tienda. Django NO debe gestionar (crear/alterar/borrar) esta tabla:
    managed = False evita que aparezca en makemigrations/migrate."""
    alias = models.CharField(max_length=200)
    producto = models.ForeignKey(
        Products, on_delete=models.DO_NOTHING, db_column='producto_id', related_name='alias_set'
    )
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'products_productalias'
        verbose_name = 'un alias de producto'
        verbose_name_plural = 'Alias de productos'

    def __str__(self):
        return self.alias
