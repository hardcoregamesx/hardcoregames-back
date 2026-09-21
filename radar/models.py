# -*- coding: utf-8 -*-
"""Modelos del radar de ofertas de tiendas digitales (Xbox / PlayStation).

Esta app es deliberadamente independiente de `products`: `products` NO tiene
migraciones (su esquema se administra por fuera de Django), asi que cualquier
relacion formal hacia sus modelos haria imposible migrar esta app. Por eso el
vinculo con el catalogo propio se guarda como un entero suelto
(`JuegoDetectado.producto_existente_id`) y no como ForeignKey.

Ver docs/radar-ofertas.md.
"""
from decimal import Decimal

from django.db import models

TIENDAS = [
    ('XBOX', 'Xbox'),
    ('PS', 'PlayStation'),
]

# Region de referencia: contra este precio compara el cliente y sobre el se
# calcula el precio de venta.
REGION_REFERENCIA = 'CO'


class ParametrosRadar(models.Model):
    """Parametros de negocio, editables desde el admin sin tocar codigo."""

    factor_precio_venta = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal('0.80'),
        help_text='El precio de venta se calcula como precio_colombia x este factor. '
                  '0.80 = el cliente ahorra 20%.',
    )
    margen_minimo_cop = models.BigIntegerField(
        default=20000,
        help_text='Ganancia minima en pesos para que una oferta se considere viable.',
    )
    descuento_minimo_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('10'),
        help_text='Descuento minimo en la tienda de origen para tener en cuenta la oferta.',
    )
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'parametros del radar'
        verbose_name_plural = 'Parametros del radar'

    def __str__(self):
        return 'Parametros del radar'

    @classmethod
    def actuales(cls):
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj


class TasaCambio(models.Model):
    """Cuantos pesos colombianos vale una unidad de cada moneda.

    Las marcadas como `manual` NO se sobrescriben al actualizar tasas: es el caso
    del dolar, que se consigue por debajo de la TRM y cuyo costo real solo lo
    sabe el dueno del negocio.
    """

    moneda = models.CharField(max_length=3, primary_key=True)
    cop_por_unidad = models.DecimalField(max_digits=18, decimal_places=6)
    manual = models.BooleanField(
        default=False,
        help_text='Si esta marcada, el actualizador automatico no la toca.',
    )
    nota = models.CharField(max_length=200, blank=True, default='')
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'una tasa de cambio'
        verbose_name_plural = 'Tasas de cambio'
        ordering = ['moneda']

    def __str__(self):
        return '%s = %s COP' % (self.moneda, self.cop_por_unidad)

    @classmethod
    def mapa(cls):
        return {t.moneda: t.cop_por_unidad for t in cls.objects.all()}


class JuegoDetectado(models.Model):
    """Un juego visto por el radar, con su ficha y su precio de referencia en Colombia."""

    tienda = models.CharField(max_length=8, choices=TIENDAS)
    id_externo = models.CharField(max_length=64, help_text='bigId en Xbox; concept id en PlayStation.')

    titulo = models.CharField(max_length=300)
    descripcion = models.TextField(blank=True, default='')
    imagen = models.CharField(max_length=700, blank=True, default='')
    generos = models.CharField(max_length=300, blank=True, default='')
    clasificacion = models.CharField(max_length=80, blank=True, default='')
    plataformas = models.CharField(max_length=160, blank=True, default='')
    desarrollador = models.CharField(max_length=200, blank=True, default='')

    # Senal de popularidad que da la propia tienda.
    rating = models.FloatField(default=0)
    rating_conteo = models.IntegerField(default=0)

    # Precio de la tienda colombiana: el ancla contra la que compara el cliente.
    precio_co = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    precio_co_oferta = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    comprable_co = models.BooleanField(default=True)

    # Vinculo suelto con el catalogo propio (ver docstring del modulo).
    producto_existente_id = models.IntegerField(null=True, blank=True)

    visto_primero = models.DateTimeField(auto_now_add=True)
    visto_ultimo = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'un juego detectado'
        verbose_name_plural = 'Juegos detectados'
        unique_together = [('tienda', 'id_externo')]
        ordering = ['titulo']

    def __str__(self):
        return '[%s] %s' % (self.get_tienda_display(), self.titulo)

    @property
    def precio_co_vigente(self):
        """Lo que pagaria hoy el cliente comprando solo en la tienda colombiana."""
        if self.precio_co_oferta and self.precio_co and 0 < self.precio_co_oferta < self.precio_co:
            return self.precio_co_oferta
        return self.precio_co

    def precio_venta_sugerido(self, parametros=None):
        base = self.precio_co_vigente
        if not base:
            return None
        parametros = parametros or ParametrosRadar.actuales()
        return int(base * parametros.factor_precio_venta)

    def mejor_precio(self):
        """El precio regional mas barato que ademas se pueda comprar de verdad."""
        candidatos = [p for p in self.precios.all() if p.comprable and p.costo_cop]
        return min(candidatos, key=lambda p: p.costo_cop) if candidatos else None


class PrecioRegional(models.Model):
    """Precio de un juego en una region de compra, ya convertido a pesos."""

    juego = models.ForeignKey(JuegoDetectado, related_name='precios', on_delete=models.CASCADE)
    region = models.CharField(max_length=2)
    moneda = models.CharField(max_length=3)

    precio_lista = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    precio_oferta = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    descuento_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0'))

    # Critico: en algunas regiones el juego aparece con precio pero no se puede
    # comprar (censura por clasificacion en Arabia Saudita, por ejemplo). Sin
    # este filtro el comparador muestra oportunidades fantasma.
    comprable = models.BooleanField(default=False)

    fecha_fin = models.DateTimeField(null=True, blank=True, help_text='Cuando vence la promocion.')
    costo_cop = models.BigIntegerField(null=True, blank=True, help_text='Precio de oferta convertido a pesos.')

    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'un precio regional'
        verbose_name_plural = 'Precios regionales'
        unique_together = [('juego', 'region')]
        ordering = ['region']

    def __str__(self):
        return '%s %s %s' % (self.region, self.moneda, self.precio_oferta)

    def margen(self, precio_venta):
        if precio_venta is None or self.costo_cop is None:
            return None
        return int(precio_venta) - int(self.costo_cop)


class EjecucionRadar(models.Model):
    """Bitacora de cada corrida.

    Un radar roto en silencio muestra precios viejos y hace vender a perdida:
    aqui queda el rastro para poder alertar.
    """

    tienda = models.CharField(max_length=8, choices=TIENDAS)
    regiones = models.CharField(max_length=120, blank=True, default='')
    inicio = models.DateTimeField(auto_now_add=True)
    fin = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    juegos_vistos = models.IntegerField(default=0)
    precios_guardados = models.IntegerField(default=0)
    error = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'una ejecucion del radar'
        verbose_name_plural = 'Ejecuciones del radar'
        ordering = ['-inicio']

    def __str__(self):
        estado = 'OK' if self.ok else 'FALLO'
        return '%s %s %s' % (self.get_tienda_display(), self.inicio.strftime('%Y-%m-%d %H:%M'), estado)
