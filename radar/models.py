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
    # Un juego que sale en las dos generaciones se vende con UNA cuenta que
    # sirve en las dos. Publicar una variante por generacion obliga al cliente
    # a elegir consola cuando no hay nada que elegir, y duplica el selector.
    consola_xbox_ambas = models.ForeignKey(
        'products.Consoles', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Consola Xbox (ambas generaciones)',
        help_text='Se usa cuando el juego sale en Xbox One y Xbox Series a la vez, en vez de '
                  'publicarlo en las dos por separado. Vacia = se busca sola una consola '
                  'llamada "Xbox".',
    )
    consola_ps_ambas = models.ForeignKey(
        'products.Consoles', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Consola PlayStation (ambas generaciones)',
        help_text='Igual que la anterior, para PS4 + PS5. Vacia = se publica en las dos por '
                  'separado, porque no hay una consola "PlayStation" generica en el catalogo.',
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
        default=999,
        help_text='Cuantas ventas acepta cada producto publicado. NO es inventario: estos '
                  'juegos son sobre pedido, no hay unidades que se acaben, asi que lo normal '
                  'es dejarlo alto (999). Bajarlo solo sirve para poner un tope de pedidos '
                  'antes de revisar a mano; en 1, el segundo cliente ve "agotado".',
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

    def consola_ambas(self, tienda):
        """La consola que cubre las dos generaciones de una familia.

        Si no esta configurada se busca por nombre: el catalogo ya tiene una
        consola "Xbox" sin generacion, y el resto del proyecto la localiza
        asi (products/views.py, managePriceFile.py). En PlayStation no existe
        equivalente, asi que sin configurar se publica en PS4 y PS5 aparte.
        """
        from products.models import Consoles

        if tienda == 'XBOX':
            if self.consola_xbox_ambas_id:
                return self.consola_xbox_ambas
            if not hasattr(self, '_xbox_generica'):
                self._xbox_generica = Consoles.objects.filter(descripcion__iexact='xbox').first()
            return self._xbox_generica
        return self.consola_ps_ambas if self.consola_ps_ambas_id else None


class MapeoConsola(models.Model):
    """Que consola del catalogo corresponde a cada plataforma de la tienda.

    Un juego casi nunca sale en una sola consola: 76 de cada 100 ofertas de
    Xbox vienen como "XboxOne, XboxSeriesX". Publicar con una consola fija
    perdia esa informacion y dejaba el producto mal etiquetado.

    Las plataformas que llegan hoy de Xbox son XboxOne, XboxSeriesX, PC y
    Handheld. Dejar la consola vacia es la forma de decir "esta plataforma no
    me interesa": PC y Handheld normalmente se ignoran.
    """

    plataforma = models.CharField(
        max_length=40, unique=True,
        help_text='Nombre tal como lo manda la tienda. Ej: XboxOne, XboxSeriesX, PS5.',
    )
    consola = models.ForeignKey(
        'products.Consoles', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', help_text='Consola de tu catalogo. Vacia = ignorar esta plataforma.',
    )
    # PC no se vende como cuenta primaria o secundaria: va con su propia
    # licencia. Con esto, una plataforma puede saltarse las licencias normales.
    licencia = models.ForeignKey(
        'products.Licenses', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Licencia exclusiva (solo PC)',
        help_text='DEJAR VACIA en Xbox y PlayStation. Vacia = el juego se publica con las '
                  'licencias normales: codigo y cuenta (primaria y secundaria). Llenarla '
                  'significa "esta plataforma se vende UNICAMENTE con esta licencia", que es '
                  'el caso de PC. Usa el precio de codigo del juego; si no tiene, el de cuenta.',
    )
    activa = models.BooleanField(default=True)

    class Meta:
        managed = False
        verbose_name = 'un mapeo de consola'
        verbose_name_plural = 'Consolas por plataforma'
        ordering = ['plataforma']

    def __str__(self):
        return '%s -> %s' % (self.plataforma, self.consola or 'sin asignar')

    @classmethod
    def mapa(cls):
        """plataforma -> (consola, licencia_solo_de_esa_plataforma o None)."""
        return {m.plataforma.lower(): (m.consola, m.licencia)
                for m in cls.objects.filter(activa=True).select_related('consola', 'licencia')
                if m.consola_id}


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

    def consolas_publicacion(self, parametros=None, colapsar=True):
        """Las consolas del catalogo en las que sale este juego.

        Un juego casi nunca sale en una sola: la tienda manda "XboxOne,
        XboxSeriesX" y hay que publicarlo en las dos, o el producto queda mal
        etiquetado y el cliente no lo encuentra filtrando por su consola.

        Pero cuando sale en las DOS generaciones de una familia, la cuenta es
        una sola y sirve en las dos: ahi se colapsa en una consola generica
        ("Xbox"). Sin eso el cliente veia cuatro variantes al mismo precio --
        primaria y secundaria de Xbox One, primaria y secundaria de Series --
        y parecia que estaba eligiendo algo.

        `colapsar=False` devuelve las consolas sin agrupar, que es lo que se
        guarda en el producto para que el filtro del catalogo lo encuentre por
        cualquiera de las dos generaciones.

        Si el juego tiene consola elegida a mano, manda esa. Si ninguna
        plataforma esta mapeada, cae a la consola por defecto de la tienda.
        """
        if self.consola_id:
            return [(self.consola, None)]

        parametros = parametros or ParametrosRadar.actuales()
        mapa = MapeoConsola.mapa()
        partes = [p.strip().lower() for p in (self.plataformas or '').split(',') if p.strip()]

        # Si sale en las dos generaciones de una familia, una sola consola que
        # las cubre: es la misma cuenta y funciona en las dos. Cuatro variantes
        # -- primaria y secundaria de cada generacion -- al mismo precio hacen
        # que el cliente crea que esta eligiendo algo.
        encontradas = []
        vistas = set()
        consumidas = set()
        familias = ()
        if colapsar:
            familias = (
                (('xboxone', 'xboxseriesx'), parametros.consola_ambas('XBOX')),
                (('ps4', 'ps5'), parametros.consola_ambas('PS')),
            )
        for miembros, consola in familias:
            if consola is None or not all(m in partes for m in miembros):
                continue
            consumidas.update(miembros)
            if consola.pk not in vistas:
                vistas.add(consola.pk)
                encontradas.append((consola, None))

        for parte in partes:
            if parte in consumidas:
                continue
            par = mapa.get(parte)
            if par is None:
                continue
            consola, licencia = par
            if consola.pk in vistas:
                continue
            vistas.add(consola.pk)
            encontradas.append((consola, licencia))
        if encontradas:
            return encontradas

        defecto = parametros.consola_xbox if self.tienda == 'XBOX' else parametros.consola_ps
        return [(defecto, None)] if defecto else []

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

    def _motivo_sin_variantes(self, parametros, destinos):
        """Por que esta configuracion no genera ninguna variante vendible.

        Esto no era un error hasta que se vio en la tienda: un juego con solo
        precio de cuenta, con las licencias primaria/secundaria sin configurar,
        se publicaba "bien" y creaba un producto sin una sola variante. La
        landing lo mostraba con precio (lo saca de la tabla del radar), pero la
        ficha lo mostraba en $0 y con el boton de "solicitar orden de compra":
        el frontend cae a ese modo cuando no encuentra ninguna variante con
        stock y precio. Un producto que no se puede comprar es peor que uno que
        no se publico, asi que ahora se avisa aqui, con el nombre de lo que
        falta configurar.
        """
        if self.precio_cuenta and not self.precio_venta:
            if parametros.licencia_primaria is None and parametros.licencia_secundaria is None:
                return (
                    'Solo tiene precio de cuenta, y en Parametros del radar no hay licencia '
                    'primaria ni secundaria. Sin ellas no hay nada que publicar: '
                    'configuralas, o ponle tambien precio de codigo.')
            return (
                'Sus plataformas ("%s") no producen ninguna variante. Revisa en Consolas por '
                'plataforma que tengan consola asignada.' % (self.plataformas or '?'))
        return (
            'La configuracion actual no produce ninguna variante (%s consola(s), licencia '
            'por defecto %s). Revisa las licencias en Parametros del radar.'
            % (len(destinos), parametros.licencia_default or 'sin configurar'))

    def variantes_vendibles(self):
        """Cuantas variantes de este juego puede comprar un cliente hoy.

        Mismo criterio que usa la ficha del producto (stock y precio mayores
        que cero). Cero significa que el producto esta en la tienda pero no se
        puede comprar.
        """
        from products.models import GameDetail

        if not self.producto_publicado_id:
            return 0
        return GameDetail.objects.filter(
            producto_id=self.producto_publicado_id, stock__gt=0, precio__gt=0).count()

    def plan_de_publicacion(self, parametros=None):
        """Que variantes habria que crear, sin escribir nada.

        Esta separado de publicar() para poder preguntar "¿por que este juego
        no se puede publicar?" sin tocar la base: publicar() lo usa para
        validar, y radar_revisar para explicar. Una sola definicion de lo que
        hace falta, en vez de dos que se desincronizan.

        Devuelve (destinos, plan). Lanza ValueError con un mensaje legible
        cuando falta algo por configurar.
        """
        parametros = parametros or ParametrosRadar.actuales()

        if not self.precio_venta and not self.precio_cuenta:
            raise ValueError(
                'No tiene ningun precio. Ponle el de codigo, el de cuenta o los dos.')

        destinos = self.consolas_publicacion(parametros)
        if not destinos:
            raise ValueError(
                'Ninguna de sus plataformas ("%s") tiene consola asignada. Asignalas en '
                'Consolas por plataforma, o pon una consola por defecto en Parametros '
                'del radar.' % (self.plataformas or '?'))

        licencia = self.licencia or parametros.licencia_default
        if licencia is None:
            raise ValueError('Falta la licencia por defecto en Parametros del radar.')

        if parametros.tipo_producto is None:
            raise ValueError('Falta el tipo de producto por defecto en Parametros del radar.')

        # Con stock 0 la variante existe pero la ficha la ignora: el frontend
        # solo mira las variantes con stock y precio, y sin ninguna cae al modo
        # "producto fisico" -- precio $0 y boton de "solicitar orden de compra".
        if parametros.stock_publicacion < 1:
            raise ValueError(
                'El stock de publicacion esta en %s. Con 0 el producto sale sin precio y sin '
                'boton de compra. Ponlo en al menos 1 en Parametros del radar.'
                % parametros.stock_publicacion)

        plan = []
        for cons, licencia_propia in destinos:
            if licencia_propia is not None:
                # Plataforma con licencia exclusiva (el caso de PC): una sola
                # variante. Se prefiere el precio de codigo, pero si no hay se
                # usa el de cuenta -- en la tienda de Microsoft un mismo
                # producto cubre Xbox y PC (Play Anywhere), asi que la cuenta
                # que se compra ya trae el juego en PC y dejarlo sin publicar
                # era regalar una venta que no cuesta nada extra.
                precio = self.precio_venta or self.precio_cuenta
                if precio:
                    plan.append((licencia_propia, precio, cons))
                continue
            if self.precio_venta:
                plan.append((licencia, self.precio_venta, cons))
            if self.precio_cuenta:
                for lic in (parametros.licencia_primaria, parametros.licencia_secundaria):
                    if lic is not None and not (self.precio_venta and lic.pk == licencia.pk):
                        plan.append((lic, self.precio_cuenta, cons))

        if not plan:
            raise ValueError(self._motivo_sin_variantes(parametros, destinos))
        return destinos, plan

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
        destinos, plan = self.plan_de_publicacion(parametros)

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

        # Las consolas del producto NO son las de las variantes. La variante
        # colapsada dice "Xbox" -- una sola opcion para el cliente, porque la
        # cuenta sirve en las dos --, pero el filtro del catalogo busca por
        # esta lista: si solo guardara la generica, quien filtra por Xbox One
        # no encontraria el juego. Asi el badge del titulo tambien queda
        # diciendo la verdad: "Xbox Series / Xbox One".
        etiquetas = self.consolas_publicacion(parametros, colapsar=False) or destinos
        producto.consola.set([cons for cons, _ in etiquetas])

        def _variante(lic, precio, cons):
            v = GameDetail.objects.filter(
                producto=producto, consola=cons, licencia=lic,
            ).first()
            if v is None:
                v = GameDetail(producto=producto, consola=cons, licencia=lic)
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
        # Hay una variante por cada consola en la que sale el juego.
        vivas = [_variante(lic, precio, cons).pk for lic, precio, cons in plan]

        # Lo que este producto tenia y ya no esta en el plan se queda en stock
        # 0. Pasa al borrar un precio: quitar el de cuenta dejaba las variantes
        # de primaria y secundaria a la venta al precio viejo, que es
        # exactamente lo que se quiso dejar de ofrecer. No se borran porque
        # pueden estar en el historial de una venta.
        GameDetail.objects.filter(producto=producto).exclude(pk__in=vivas).update(stock=0)

        # Ojo: NO se escriben aqui `consola` ni `licencia`. Esos dos campos son
        # el override manual ("para este juego quiero esta consola"), y
        # rellenarlos con lo que se acaba de usar ataria el juego a una sola
        # consola en la siguiente publicacion -- justo lo contrario de publicar
        # en todas las que sale.
        self.producto_publicado_id = producto.id_product
        self.publicado_en = timezone.now()
        self.estado = 'publicado'
        self.save(update_fields=['producto_publicado_id', 'publicado_en', 'estado'])
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
