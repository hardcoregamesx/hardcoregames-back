from django.contrib.auth.models import User
from django.db import models

from products.models import Transactions

# ----------------------------------------------------------------------- #
#  Todas las tablas de este modulo se crean a mano por SQL directo (ver    #
#  membership/sql/2026_09_08_create_membership_tables.sql), igual que      #
#  ProductAlias/CouponPurgeLog en products y las tablas de rewards. Este   #
#  proyecto no usa `migrate` en ningun app: managed = False en todo lo de  #
#  abajo evita que makemigrations/migrate intente crearlas, alterarlas o   #
#  borrarlas.                                                              #
# ----------------------------------------------------------------------- #

TIER_CHOICES = [
    ('LOW', 'Bajo'),
    ('MID', 'Intermedio'),
    ('HIGH', 'Alto'),
]

STATUS_CHOICES = [
    ('ACTIVE', 'Activa'),
    ('INACTIVE', 'Inactiva'),
]


class YoutubeMembershipLink(models.Model):
    """Vinculo 1 a 1 entre una cuenta de hardcoregames.co y un canal de
    YouTube. `status` solo lo cambia el sync diario (nunca el flujo de
    conexion): completar el OAuth no prueba ser miembro pago, solo la lista
    real de members.list del creador lo hace.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, db_column='user_id', related_name='youtube_membership')
    youtube_channel_id = models.CharField(max_length=64, unique=True)
    youtube_display_name = models.CharField(max_length=255, blank=True, default='')
    tier = models.CharField(max_length=10, choices=TIER_CHOICES, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='INACTIVE')
    linked_at = models.DateTimeField()
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'membership_youtubemembershiplink'
        verbose_name = 'vínculo de YouTube'
        verbose_name_plural = 'Vínculos de YouTube'
        ordering = ['-linked_at']

    def __str__(self):
        return f'{self.user} ↔ {self.youtube_channel_id} ({self.status})'


class MembershipLevelMapping(models.Model):
    """Traduce el nombre real del nivel de membresia configurado en YouTube
    Studio (texto libre, lo define el dueño del canal) a uno de nuestros
    tres tiers. Editable desde el admin sin necesitar un deploy.
    """

    google_level_name = models.CharField(max_length=255, unique=True, help_text='Nombre exacto del nivel en YouTube Studio → Monetización → Membresías.')
    tier = models.CharField(max_length=10, choices=TIER_CHOICES)

    class Meta:
        managed = False
        db_table = 'membership_levelmapping'
        verbose_name = 'mapeo de nivel'
        verbose_name_plural = 'Mapeo de niveles'

    def __str__(self):
        return f'{self.google_level_name} → {self.get_tier_display()}'


class MembershipPointsClaim(models.Model):
    """Un reclamo semanal de puntos VIP. El unique_together es lo unico que
    hace falta para 'una vez por semana, sin acumular atrasos': una semana
    no reclamada simplemente queda inalcanzable en cuanto pasa.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column='user_id', related_name='membership_points_claims')
    week_start_date = models.DateField(help_text='Lunes de la semana ISO reclamada.')
    points_awarded = models.IntegerField()
    claimed_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'membership_pointsclaim'
        verbose_name = 'reclamo de puntos VIP'
        verbose_name_plural = 'Reclamos de puntos VIP'
        ordering = ['-claimed_at']
        unique_together = ('user', 'week_start_date')

    def __str__(self):
        return f'{self.user} +{self.points_awarded} ({self.week_start_date})'


class MembershipDiscountLog(models.Model):
    """Auditoria de cada vez que el descuento VIP se aplico de verdad en un
    checkout. Existe porque el negocio pidio explicitamente poder medir el
    impacto real en margen de este descuento.
    """

    transaction = models.ForeignKey(Transactions, on_delete=models.CASCADE, db_column='transaction_id', related_name='membership_discounts')
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column='user_id', related_name='membership_discount_logs')
    tier = models.CharField(max_length=10, choices=TIER_CHOICES)
    percent_applied = models.DecimalField(max_digits=5, decimal_places=2)
    amount_saved = models.IntegerField()
    applied_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'membership_discountlog'
        verbose_name = 'descuento VIP aplicado'
        verbose_name_plural = 'Descuentos VIP aplicados'
        ordering = ['-applied_at']

    def __str__(self):
        return f'{self.user} -{self.amount_saved} ({self.percent_applied}%)'


class GoogleOAuthCredential(models.Model):
    """Credenciales OAuth de servidor a servidor (no de un miembro
    cualquiera: solo la del dueño del canal, scope
    youtube.channel-memberships.creator, capturada una sola vez en la Fase 0
    manual). Vive en la base y no en un .env para poder rotarla desde el
    admin sin redeploy.
    """

    provider = models.CharField(max_length=30, unique=True, help_text="Ej. 'youtube_creator'.")
    refresh_token = models.TextField()
    access_token_cache = models.TextField(blank=True, default='')
    access_token_expires_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'membership_googleoauthcredential'
        verbose_name = 'credencial OAuth de Google'
        verbose_name_plural = 'Credenciales OAuth de Google'

    def __str__(self):
        return self.provider
