# -*- coding: utf-8 -*-
"""Modelos del radar de ofertas de tiendas digitales (Xbox / PlayStation).

Este proyecto NO usa `migrate` en ningun app (ver la cabecera de
membership/models.py). El `users` declara una relacion hacia `auth.User` sin
tener migraciones propias, asi que Django se niega a construir el grafo de
migraciones para cualquier app. Por eso aqui, como en membership, rewards y las
tablas nuevas de products: `managed = False` y el esquema se crea con SQL
directo desde radar/sql/2026-09-radar.sql, que es la fuente de verdad.

Ademas esta app es independiente de `products`: el vinculo con el catalogo
propio se guarda como un entero suelto (`JuegoDetectado.producto_existente_id`)
y no como ForeignKey.

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

ESTADOS = [
    ('nuevo', 'Nuevo'),
    ('aprobado', 'Aprobado'),
    ('publicado', 'Publicado'),
    ('descartado', 'Descartado'),
    ('vencido', 'Vencido'),
]


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

    # Valores por defecto al publicar, para no elegirlos juego por juego.
    consola_xbox = models.ForeignKey(
        'products.Consoles', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', help_text='Consola que se asigna a los juegos de Xbox al publicarlos.',
    )
    consola_ps = models.ForeignKey(
        'products.Consoles', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', help_text='Consola que se asigna a los juegos de PlayStation al publicarlos.',
    )
    licencia_default = models.ForeignKey(
        'products.Licenses', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+',
        help_text='Licencia principal. El "precio sugerido" del listado es para ESTA licencia.',
    )

    # Una cuenta no se vende al mismo precio que un codigo, pero primaria y
    # secundaria comparten precio. Queda VACIO a proposito: hasta que se llene,
    # el radar publica solo el codigo y no inventa precios de cuentas. En una
    # tienda viva, que falte una variante es menos grave que un precio inventado.
    licencia_primaria = models.ForeignKey(
        'products.Licenses', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', help_text='Licencia de cuenta primaria. Dejar vacia para no publicarla.',
    )
    licencia_secundaria = models.ForeignKey(
        'products.Licenses', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', help_text='Licencia de cuenta secundaria. Dejar vacia para no publicarla.',
    )
    factor_cuenta = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True,
        help_text='Precio de cuenta (primaria y secundaria por igual) = precio_colombia x este '
                  'numero. Ej: 0.45 deja el juego al 45% de lo que cuesta en la tienda.',
    )
    tipo_producto = models.ForeignKey(
        'products.ProductsType', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', help_text='Tipo de producto del catalogo con el que se crean los publicados.',
    )
    stock_publicacion = models.IntegerField(
        default=10,
        help_text='Cuantas unidades queda disponible cada producto publicado. No es stock '
                  'real: es cuantas ventas se aceptan antes de revisarlo a mano.',
    )

    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
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


class Franquicia(models.Model):
    """Nombres que valen la pena mirar, aunque el numero no lo diga.

    El radar trae cientos de ofertas por ciclo y la mayoria son juegos que
    nadie pide. Las resenas de la tienda filtran bastante, pero no todo: un
    juego de una saga conocida puede tener pocas resenas en Xbox y aun asi
    venderse aqui. Esa lista es criterio del dueno, no un dato que se pueda
    deducir, y por eso se edita a mano.

    El termino se busca dentro del titulo, sin distinguir mayusculas: "batman"
    encuentra "Batman: Arkham Knight" y "BATMAN - Edicion Definitiva".
    """

    termino = models.CharField(
        max_length=80, unique=True,
        help_text='Trozo del titulo a buscar. Ej: "call of duty", "batman", "borderlands".',
    )
    activa = models.BooleanField(default=True)
    nota = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        managed = False
        verbose_name = 'una franquicia vigilada'
        verbose_name_plural = 'Franquicias vigiladas'
        ordering = ['termino']

    def __str__(self):
        return self.termino

    @classmethod
    def terminos_activos(cls):
        return list(cls.objects.filter(activa=True).values_list('termino', flat=True))


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
        managed = False
        verbose_name = 'una tasa de cambio'
        verbose_name_plural = 'Tasas de cambio'
        ordering = ['moneda']

    def __str__(self):
        return '%s = %s COP' % (self.moneda, self.cop_por_unidad)

    @classmethod
    def mapa(cls):
        return {t.moneda: t.cop_por_unidad for t in cls.objects.all()}


class TasaTienda(models.Model):
    """Cuanto cuesta un dolar de SALDO en cada tienda, que no es un dolar normal.

    El dueno no compra dolares para gastar en la tienda: compra gift cards, y
    esas se consiguen con descuento en buysellvouchers.com. Un dolar de saldo
    de Xbox sale por ~0,91 USD y uno de PSN por ~0,93: son dos tasas distintas,
    y esa diferencia es margen que ninguna API de divisas conoce.

    El costo final en pesos se compone: `factor` (el descuento de la gift card,
    que se lee a diario) x lo que cuesta un dolar de verdad (TasaCambio['USD'],
    editable a mano).
    """

    tienda = models.CharField(max_length=8, primary_key=True, choices=TIENDAS)
    factor = models.DecimalField(
        max_digits=8, decimal_places=6,
        help_text='Dolares que cuesta 1 dolar de saldo. 0.91 = 9% de descuento.',
    )
    muestras = models.IntegerField(
        default=0, help_text='Cuantas ofertas se leyeron para calcularlo.')
    manual = models.BooleanField(
        default=False, help_text='Si esta marcada, el actualizador automatico no la toca.')
    nota = models.CharField(max_length=300, blank=True, default='')
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        verbose_name = 'una tasa por tienda'
        verbose_name_plural = 'Tasas por tienda (dolar de saldo)'
        ordering = ['tienda']

    def __str__(self):
        return '%s: 1 USD de saldo = %s USD' % (self.get_tienda_display(), self.factor)

    @property
    def cop_por_dolar(self):
        """Pesos que cuesta un dolar de saldo de esta tienda."""
        usd = TasaCambio.objects.filter(moneda='USD').first()
        if usd is None:
            return None
        return (self.factor * usd.cop_por_unidad).quantize(Decimal('0.01'))

    @classmethod
    def mapa(cls):
        return {t.tienda: t for t in cls.objects.all()}


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

    # --- Aprobacion y publicacion ---
    estado = models.CharField(max_length=12, choices=ESTADOS, default='nuevo')
    # Dos precios por juego, no uno. Un mismo titulo se puede ofrecer como
    # codigo, como cuenta, o como las dos cosas: dejar un precio vacio es la
    # forma de decir "esta no la ofrezco". El radar sugiere ambos al aprobar,
    # pero la ultima palabra es del dueno.
    precio_venta = models.BigIntegerField(
        null=True, blank=True, verbose_name='Precio codigo',
        help_text='Precio en pesos como codigo. Vacio = no se ofrece como codigo.',
    )
    precio_cuenta = models.BigIntegerField(
        null=True, blank=True, verbose_name='Precio cuenta',
        help_text='Precio en pesos como cuenta (primaria y secundaria por igual). '
                  'Vacio = no se ofrece como cuenta.',
    )
    region_compra = models.CharField(
        max_length=2, blank=True, default='',
        help_text='Region elegida para comprarlo. Se congela al aprobar.',
    )
    consola = models.ForeignKey(
        'products.Consoles', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    licencia = models.ForeignKey(
        'products.Licenses', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    producto_publicado_id = models.IntegerField(null=True, blank=True)
    publicado_en = models.DateTimeField(null=True, blank=True)

    visto_primero = models.DateTimeField(auto_now_add=True)
    visto_ultimo = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
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
        """Sugerido para la licencia principal (la de Parametros)."""
        base = self.precio_co_vigente
        if not base:
            return None
        parametros = parametros or ParametrosRadar.actuales()
        return int(base * parametros.factor_precio_venta)

    def precio_cuenta_sugerido(self, parametros=None):
        base = self.precio_co_vigente
        parametros = parametros or ParametrosRadar.actuales()
        if not base or not parametros.factor_cuenta:
            return None
        return int(base * parametros.factor_cuenta)

    def sugeridos_por_licencia(self, parametros=None):
        """Precio sugerido para cada licencia configurada.

        Existe porque un codigo y una cuenta no valen lo mismo: mostrar un solo
        numero sin decir de que licencia habla induce a publicar una cuenta al
        precio de un codigo. Devuelve [(nombre_licencia, precio), ...] y solo
        incluye las licencias que esten configuradas.
        """
        base = self.precio_co_vigente
        if not base:
            return []
        parametros = parametros or ParametrosRadar.actuales()
        filas = []
        combinaciones = (
            (parametros.licencia_default, parametros.factor_precio_venta),
            (parametros.licencia_primaria, parametros.factor_cuenta),
            (parametros.licencia_secundaria, parametros.factor_cuenta),
        )
        for licencia, factor in combinaciones:
            if licencia is None or not factor:
                continue
            filas.append((str(licencia), int(base * factor)))
        return filas

    def mejor_precio(self):
        """El precio regional mas barato que ademas se pueda comprar de verdad."""
        candidatos = [p for p in self.precios.all() if p.comprable and p.costo_cop]
        return min(candidatos, key=lambda p: p.costo_cop) if candidatos else None

    @property
    def vence(self):
        """Cuando muere la promocion en la region elegida (o en la mas barata)."""
        elegido = None
        if self.region_compra:
            elegido = next((p for p in self.precios.all() if p.region == self.region_compra), None)
        elegido = elegido or self.mejor_precio()
        return elegido.fecha_fin if elegido else None

    def preparar(self, parametros=None):
        """Deja el juego listo para publicar: region congelada y precios puestos.

        Se separa de `publicar` porque tambien la usa la accion "Aprobar", pero
        `publicar` la llama sola: quien ya escribio los precios no tiene por que
        dar dos pasos. Nunca pisa un precio escrito a mano.

        Devuelve False si no hay ninguna region donde se pueda comprar.
        """
        parametros = parametros or ParametrosRadar.actuales()
        mejor = self.mejor_precio()
        if mejor is None:
            return False

        cambios = []
        if not self.region_compra:
            # Sin esto la landing no sabe de que promocion sacar la fecha, y las
            # tarjetas saldrian sin cuenta atras.
            self.region_compra = mejor.region
            cambios.append('region_compra')
        if not self.precio_venta and not self.precio_cuenta:
            self.precio_venta = self.precio_venta_sugerido(parametros)
            self.precio_cuenta = self.precio_cuenta_sugerido(parametros)
            cambios += ['precio_venta', 'precio_cuenta']
        if cambios:
            self.save(update_fields=cambios)
        return True

    def publicar(self, parametros=None):
        """Crea (o actualiza) el producto real del catalogo para este juego.

        Se publica como producto normal a proposito: asi el carrito, las
        pasarelas y los correos que ya existen funcionan sin tocar nada.

        Dos diferencias con un producto de catalogo:

        1. `sobre_pedido = True`, que cambia la promesa de entrega en el
           frontend (no es inmediata: se entrega en horario de tienda).
        2. La variante se publica en modo **reserva** con el anticipo igual al
           precio total. Eso es lo que hace que funcione sin tener la cuenta:
           el checkout de reserva no crea SaleDetail ni manda credenciales
           (docs/cuotas-y-reserva.md §4.3), asi que el cliente paga, el pedido
           queda esperando, y la cuenta real se asigna despues desde
           "Planes de pago" con la accion "Entregar pedido". Sin esto, la
           primera venta fallaria al intentar leer una cuenta que no existe.

        Devuelve el producto. Lanza ValueError con un mensaje legible si falta
        algo por configurar.
        """
        from datetime import timedelta

        from django.utils import timezone
        from products.models import GameDetail, Products

        parametros = parametros or ParametrosRadar.actuales()

        if not self.precio_venta and not self.precio_cuenta:
            raise ValueError(
                '"%s" no tiene ningun precio. Ponle el de codigo, el de cuenta o los dos.'
                % self.titulo)

        consola = self.consola or (
            parametros.consola_xbox if self.tienda == 'XBOX' else parametros.consola_ps
        )
        if consola is None:
            raise ValueError(
                'Falta la consola por defecto para %s. Configurala en Parametros del radar.'
                % self.get_tienda_display()
            )

        licencia = self.licencia or parametros.licencia_default
        if licencia is None:
            raise ValueError('Falta la licencia por defecto. Configurala en Parametros del radar.')

        if parametros.tipo_producto is None:
            raise ValueError('Falta el tipo de producto por defecto. Configuralo en Parametros del radar.')

        # El modo reserva exige una fecha de lanzamiento futura. Se usa el dia
        # siguiente al fin de la promocion: mientras el producto este publicado
        # esa fecha siempre esta por delante, y cuando la promocion vence el
        # producto se retira igual.
        vence = self.vence
        base = vence.date() if vence else timezone.now().date()
        fecha_lanzamiento = max(base, timezone.now().date()) + timedelta(days=1)

        producto = None
        if self.producto_publicado_id:
            producto = Products.objects.filter(id_product=self.producto_publicado_id).first()

        if producto is None:
            producto = Products.objects.create(
                title=self.titulo[:200],
                description=self.descripcion or self.titulo,
                image=self.imagen,
                type_id=parametros.tipo_producto,
                calification=self.rating_conteo,
                sobre_pedido=True,
                radar_tienda=self.tienda,
                fecha_lanzamiento=fecha_lanzamiento,
            )
        else:
            producto.title = self.titulo[:200]
            producto.description = self.descripcion or self.titulo
            producto.image = self.imagen
            producto.sobre_pedido = True
            producto.radar_tienda = self.tienda
            producto.fecha_lanzamiento = fecha_lanzamiento
            producto.save()

        producto.consola.add(consola)

        def _variante(lic, precio):
            v = GameDetail.objects.filter(
                producto=producto, consola=consola, licencia=lic,
            ).first()
            if v is None:
                v = GameDetail(producto=producto, consola=consola, licencia=lic)
            v.precio = int(precio)
            v.precio_descuento = 0
            v.stock = parametros.stock_publicacion
            # Reserva con anticipo = precio total: el cliente paga el 100% hoy
            # y no se le mandan credenciales hasta que exista la cuenta real.
            v.reserva_activa = True
            v.monto_reserva = int(precio)
            v.cuotas_activas = False
            v.save()
            return v

        # Cada precio vacio es una decision: "esta modalidad no la ofrezco".
        if self.precio_venta:
            _variante(licencia, self.precio_venta)

        if self.precio_cuenta:
            for lic in (parametros.licencia_primaria, parametros.licencia_secundaria):
                if lic is not None and not (self.precio_venta and lic.pk == licencia.pk):
                    _variante(lic, self.precio_cuenta)

        self.producto_publicado_id = producto.id_product
        self.publicado_en = timezone.now()
        self.estado = 'publicado'
        self.consola = consola
        self.licencia = licencia
        self.save(update_fields=[
            'producto_publicado_id', 'publicado_en', 'estado', 'consola', 'licencia',
        ])
        return producto

    def despublicar(self):
        """Saca el producto de circulacion sin borrar nada.

        No se borra el producto: puede estar en el historial de una venta. Se
        deja en stock 0, que es como el sitio ya marca "agotado".
        """
        from products.models import GameDetail

        if self.producto_publicado_id:
            GameDetail.objects.filter(producto_id=self.producto_publicado_id).update(stock=0)
        self.estado = 'vencido'
        self.save(update_fields=['estado'])


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
        managed = False
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
        managed = False
        verbose_name = 'una ejecucion del radar'
        verbose_name_plural = 'Ejecuciones del radar'
        ordering = ['-inicio']

    def __str__(self):
        estado = 'OK' if self.ok else 'FALLO'
        return '%s %s %s' % (self.get_tienda_display(), self.inicio.strftime('%Y-%m-%d %H:%M'), estado)
