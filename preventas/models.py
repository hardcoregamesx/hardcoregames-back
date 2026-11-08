from django.db import models
from django.utils import timezone

# --------------------------------------------------------------------- #
#  Tablas gestionadas con SQL directo (management command                #
#  `crear_tablas_preventas`), igual que sorteos/rewards: managed = False  #
#  evita que makemigrations/migrate las toque.                           #
# --------------------------------------------------------------------- #

FASE_PREVENTA = 'PREVENTA'
FASE_TARDIA = 'TARDIA'
FASE_CHOICES = [(FASE_PREVENTA, 'Preventa'), (FASE_TARDIA, 'Preventa tardía')]

ESTADO_PENDIENTE = 'PENDIENTE'
ESTADO_RESERVADA = 'RESERVADA'
ESTADO_PAGADA = 'PAGADA'
ESTADO_DESPACHADA = 'DESPACHADA'
ESTADO_EXPIRADA = 'EXPIRADA'
ESTADO_CANCELADA = 'CANCELADA'
ESTADO_REEMBOLSADA = 'REEMBOLSADA'
ESTADO_CHOICES = [
    (ESTADO_PENDIENTE, 'Pendiente de pago de la reserva'),
    (ESTADO_RESERVADA, 'Reservada (reserva pagada)'),
    (ESTADO_PAGADA, 'Saldo pagado (lista para despachar)'),
    (ESTADO_DESPACHADA, 'Despachada'),
    (ESTADO_EXPIRADA, 'Expirada (no pagó la reserva)'),
    (ESTADO_CANCELADA, 'Cancelada'),
    (ESTADO_REEMBOLSADA, 'Reembolsada'),
]

ENVIO_DIRECTO = 'DIRECTO'
ENVIO_INTERMEDIA = 'INTERMEDIA'
ENVIO_CHOICES = [
    (ENVIO_DIRECTO, 'Directo a su ciudad por transportadora'),
    (ENVIO_INTERMEDIA, 'Por ciudad intermedia y luego domicilio'),
]

FUENTE_CHOICES = [
    ('Google', 'Google'),
    ('Facebook', 'Facebook'),
    ('Instagram', 'Instagram'),
    ('Canal de WhatsApp', 'Canal de WhatsApp'),
    ('Recomendación de un amigo', 'Recomendación de un amigo'),
    ('TikTok', 'TikTok'),
    ('Cliente antiguo', 'Soy cliente antiguo'),
]


class Preventa(models.Model):
    slug = models.SlugField(max_length=80, unique=True, verbose_name='Slug (URL)',
                            help_text='Ej. metroid-prime-4. La página queda en /preventas/<slug>.')
    title = models.CharField(max_length=150, verbose_name='Título')
    description = models.TextField(blank=True, default='', verbose_name='Descripción')
    image_url = models.CharField(max_length=500, null=True, blank=True, verbose_name='Imagen (URL)')
    reserva_unit = models.IntegerField(verbose_name='Valor de reserva por unidad (COP)')
    breb_key = models.CharField(
        max_length=60, blank=True, default='', verbose_name='Llave Bre-B',
        help_text='Vacío = usa la llave general de la tienda. Debe ser una llave que VozPay esté vigilando.',
    )
    envio_nacional_est = models.IntegerField(
        default=20000, verbose_name='Envío a su ciudad (estimado, COP)',
        help_text='Solo informativo: el envío lo paga el cliente al recibir.',
    )
    permitir_abonos = models.BooleanField(
        default=False, verbose_name='Permitir abonos libres',
        help_text='El cliente puede ir abonando el monto que quiera (mínimo abajo) hasta el tope de la fase actual '
                  '(o el precio final, si ya lo fijaste).',
    )
    abono_minimo = models.IntegerField(default=10000, verbose_name='Abono mínimo (COP)')

    entrega_desde = models.DateField(
        null=True, blank=True, verbose_name='Entregas desde',
        help_text='Inicio del rango de entrega del producto físico. Se muestra como "Entregas entre el X y el Z".',
    )
    entrega_hasta = models.DateField(null=True, blank=True, verbose_name='Entregas hasta')
    enlace_externo = models.CharField(
        max_length=300, blank=True, default='', verbose_name='Enlace externo',
        help_text='Solo para preventas que se reservan en su propia página (ej. /zelda, /grandtheftautovi). '
                  'Si lo llenas, la tarjeta en /preventas lleva a ese enlace y no usa el formulario nuevo.',
    )

    pre_min = models.IntegerField(default=0, verbose_name='Preventa: precio mínimo estimado')
    pre_max = models.IntegerField(default=0, verbose_name='Preventa: precio máximo estimado')
    pre_final = models.IntegerField(
        null=True, blank=True, verbose_name='Preventa: precio FINAL',
        help_text='Al llenarlo, los clientes reservados en preventa ya pueden pagar su saldo.',
    )

    switch_at = models.DateTimeField(
        null=True, blank=True, verbose_name='Fecha de cambio a preventa tardía',
        help_text='Desde esta fecha la preventa pasa sola a "tardía". Vacío = nunca cambia.',
    )

    tardia_min = models.IntegerField(default=0, verbose_name='Tardía: precio mínimo estimado')
    tardia_max = models.IntegerField(default=0, verbose_name='Tardía: precio máximo estimado')
    tardia_final = models.IntegerField(
        null=True, blank=True, verbose_name='Tardía: precio FINAL',
        help_text='Al llenarlo, los clientes reservados en la tardía ya pueden pagar su saldo.',
    )
    tardia_disponibles = models.IntegerField(
        null=True, blank=True, verbose_name='Tardía: unidades disponibles',
        help_text='Vacío = sin tope. Baja solo con cada reserva; en 0 muestra "Agotado". Puedes editarlo a mano.',
    )

    active = models.BooleanField(default=True, verbose_name='Activa (visible en la web)')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'preventas_preventa'
        verbose_name = 'preventa'
        verbose_name_plural = 'Preventas'
        ordering = ['-created_at']

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.entrega_desde and self.entrega_hasta and self.entrega_hasta < self.entrega_desde:
            raise ValidationError({'entrega_hasta': 'Debe ser igual o posterior a "Entregas desde".'})
        if self.enlace_externo and not (self.enlace_externo.startswith('/') or self.enlace_externo.startswith('http')):
            raise ValidationError({'enlace_externo': 'Debe empezar por / (ruta del sitio) o http(s)://.'})

    def __str__(self):
        return self.title


class CiudadIntermedia(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    activa = models.BooleanField(default=True)
    costo_estimado = models.IntegerField(
        null=True, blank=True, verbose_name='Costo estimado del domicilio (COP)',
        help_text='Solo informativo, ej. 12000.',
    )
    orden = models.IntegerField(default=0)

    class Meta:
        managed = False
        db_table = 'preventas_ciudad_intermedia'
        verbose_name = 'ciudad intermedia'
        verbose_name_plural = 'Ciudades intermedias'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class Reserva(models.Model):
    codigo = models.CharField(max_length=12, unique=True)
    preventa = models.ForeignKey(Preventa, on_delete=models.PROTECT, db_column='preventa_id', related_name='reservas')
    fase = models.CharField(max_length=10, choices=FASE_CHOICES)
    unidades = models.IntegerField()
    nombre = models.CharField(max_length=150)
    whatsapp = models.CharField(max_length=30)
    direccion = models.CharField(max_length=300)
    ciudad = models.CharField(max_length=100)
    cedula = models.CharField(max_length=20)
    fuente = models.CharField(max_length=60, choices=FUENTE_CHOICES)
    envio_tipo = models.CharField(max_length=12, choices=ENVIO_CHOICES)
    ciudad_intermedia = models.CharField(max_length=80, blank=True, default='')
    reserva_total = models.IntegerField(verbose_name='Reserva total (COP)')
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    guia = models.CharField(
        max_length=300, blank=True, default='', verbose_name='Guía / domiciliario',
        help_text='Texto libre. Ej. "00127327823 - Interrapidísimo" o "3164573822 Alfonso mensajero".',
    )
    despachado_at = models.DateTimeField(null=True, blank=True, verbose_name='Fecha de despacho')
    notas = models.TextField(blank=True, default='', verbose_name='Notas internas')
    expires_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name='Reserva pagada el')
    saldo_paid_at = models.DateTimeField(null=True, blank=True, verbose_name='Saldo pagado el')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'preventas_reserva'
        verbose_name = 'reserva'
        verbose_name_plural = 'Reservas'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.codigo} · {self.nombre}'


class Pago(models.Model):
    transaction_id = models.CharField(max_length=40, unique=True)
    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, db_column='reserva_id', related_name='pagos')
    tipo = models.CharField(max_length=8)  # RESERVA | SALDO
    monto = models.IntegerField()
    status = models.CharField(max_length=12, default='pendiente')  # pendiente | approved | cancelada
    nombre_pagador = models.CharField(max_length=150, blank=True, default='')
    breb_key = models.CharField(max_length=60, blank=True, default='')
    deadline_at = models.CharField(max_length=40, blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'preventas_pago'
        verbose_name = 'pago'
        verbose_name_plural = 'Pagos'
        ordering = ['-created_at']
