from django.contrib.auth.models import User
from django.db import models

# --------------------------------------------------------------------- #
#  Todas las tablas de este modulo son gestionadas por hc-fastapi        #
#  (SQLAlchemy Base.metadata.create_all en app/models.py). Django solo   #
#  las administra via el panel: managed = False evita que                #
#  makemigrations/migrate intente crearlas, alterarlas o borrarlas.      #
#  Mismo patron que rewards.models (Roulette, RoulettePrize).            #
# --------------------------------------------------------------------- #

SORTEO_STATUS_CHOICES = [
    ('DRAFT', 'Borrador'),
    ('ACTIVE', 'Activo'),
    ('FINISHED', 'Finalizado'),
]


class Sorteo(models.Model):
    title = models.CharField(max_length=150, verbose_name='Título')
    legend = models.TextField(
        blank=True, default='', verbose_name='Leyenda',
        help_text='Ej. "Compra en Hardcore Games y gana FC 27, dos ganadores este mes de agosto".',
    )
    prize_image_url = models.CharField(
        max_length=500, null=True, blank=True, verbose_name='Imagen del premio (URL)',
        help_text='URL de la imagen, igual que el campo imagen de un producto.',
    )
    start_date = models.DateTimeField(verbose_name='Fecha de inicio')
    end_date = models.DateTimeField(verbose_name='Fecha de fin')
    min_purchases = models.IntegerField(
        null=True, blank=True, verbose_name='Compras mínimas',
        help_text='Vacío = este requisito no aplica.',
    )
    min_amount = models.IntegerField(
        null=True, blank=True, verbose_name='Valor mínimo acumulado (COP)',
        help_text='Vacío = este requisito no aplica.',
    )
    require_both = models.BooleanField(
        default=False, verbose_name='Requiere ambos requisitos',
        help_text='Si están configurados compras mínimas Y valor mínimo, marca esto para exigir los dos a la vez en vez de cualquiera de los dos.',
    )
    winners_count = models.IntegerField(default=1, verbose_name='Cantidad de ganadores')
    status = models.CharField(max_length=20, choices=SORTEO_STATUS_CHOICES, default='DRAFT', verbose_name='Estado')
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'sorteos_sorteo'
        # app_label='rewards' agrupa este modelo bajo la seccion "Hardcore
        # Rewards" del sidebar del admin (verbose_name de RewardsConfig) en
        # vez de una seccion "Sorteos" aparte al final. El modulo Python
        # sigue viviendo en la app sorteos; esto solo afecta como jazzmin
        # lo agrupa visualmente.
        app_label = 'rewards'
        verbose_name = 'sorteo'
        verbose_name_plural = 'Sorteos'
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class SorteoWinner(models.Model):
    sorteo = models.ForeignKey(Sorteo, on_delete=models.CASCADE, db_column='sorteo_id', related_name='winners')
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING, db_column='user_id', related_name='sorteo_wins')
    drawn_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'sorteos_winner'
        app_label = 'rewards'
        verbose_name = 'ganador de sorteo'
        verbose_name_plural = 'Ganadores de sorteo'
        ordering = ['-drawn_at']

    def __str__(self):
        return f'{self.user} — {self.sorteo}'


class SorteoOrderBuy(models.Model):
    """Espejo de solo-lectura de orders_buy (tabla propia de hc-fastapi),
    usado unicamente para calcular quien califica al ejecutar un sorteo.
    No se usa para crear/editar ordenes desde Django."""

    id_order = models.AutoField(primary_key=True, db_column='id_order')
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING, db_column='user_id', related_name='+')
    status = models.CharField(max_length=50)
    amount = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'orders_buy'
        verbose_name = 'orden (solo lectura)'
        verbose_name_plural = 'Órdenes (solo lectura)'
