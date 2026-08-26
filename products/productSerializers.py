from rest_framework import serializers

from products.models import Products, ShoppingCar, Licenses, GameDetail, Consoles, SaleDetail, DaysForRentail, \
    PriceForSuscription, ProductsType, VariablesSistema


class SerializerForConsole(serializers.ModelSerializer):
    class Meta:
        model = Consoles
        fields = ('pk', 'descripcion', 'estado')


class SerializerForTypeProduct(serializers.ModelSerializer):
    class Meta:
        model = ProductsType
        fields = ('pk', 'description',)


class SerializerForTypes(serializers.ModelSerializer):
    class Meta:
        model = Licenses
        fields = ('pk', 'descripcion',)


class SerializerForVariables(serializers.ModelSerializer):
    class Meta:
        model = VariablesSistema
        fields = ('nombre_variable','descripcion','valor', 'url')


class ProductsSerializer(serializers.ModelSerializer):
    consola = SerializerForConsole(read_only=True, many=True)
    tipo_juego = SerializerForTypes(read_only=True, many=False)
    type_id = SerializerForTypeProduct(read_only=True, many=False)

    class Meta:
        model = Products
        fields = (
            'pk', 'title', 'description', 'stock', 'price', 'precio_descuento', 'date_register',
            'image', 'date_last_modified', 'consola', 'type_id', 'calification', 'tipo_juego',
            'puntos_venta', 'puede_rentarse', 'destacado')


class ProductSerializer(serializers.ModelSerializer):
    consola = SerializerForConsole(read_only=True, many=True)
    tipo_juego = SerializerForTypes(read_only=True, many=False)
    type_id = SerializerForTypeProduct(read_only=True, many=False)

    class Meta:
        model = Products
        fields = (
            'pk', 'title', 'description', 'date_register',
            'image', 'date_last_modified', 'consola', 'type_id', 'calification', 'tipo_juego',
            'puntos_venta', 'puede_rentarse', 'destacado')


class ShoppingCarSerializer(serializers.ModelSerializer):
    id_product = serializers.IntegerField(source='producto.producto.id_product', read_only=True)
    id_combination = serializers.IntegerField(source='producto.id_game_detail', read_only=True)
    title_product = serializers.CharField(source='producto.producto.title', read_only=True)
    stock = serializers.IntegerField(source='producto.stock', read_only=True)
    licence = serializers.CharField(source='producto.licencia.descripcion', read_only=True)
    console = serializers.CharField(source='producto.consola.descripcion', read_only=True)
    price = serializers.SerializerMethodField()
    type = serializers.IntegerField(source='producto.producto.type_id_id', read_only=True)
    image = serializers.CharField(source='producto.producto.image', read_only=True)
    type_account = serializers.SerializerMethodField()

    class Meta:
        model = ShoppingCar
        fields = ('pk', 'id_product', 'id_combination', 'title_product', 'stock', 'price', 'licence',
                  'console', 'type', 'estado', 'image', 'type_account')

    @staticmethod
    def get_price(obj):
        return obj.producto.precio_descuento if obj.producto.precio_descuento > 0 else obj.producto.precio

    @staticmethod
    def get_type_account(obj):
        licence_value = obj.producto.licencia.descripcion
        return 2 if licence_value.lower() == 'codigo' else 1


class SerializerGameDetail(serializers.ModelSerializer):
    desc_licence = serializers.CharField(source='licencia.descripcion', read_only=True)
    desc_console = serializers.CharField(source='consola.descripcion', read_only=True)

    class Meta:
        model = GameDetail
        fields = ('pk', 'consola', 'desc_console', 'licencia', 'desc_licence',
                  'stock', 'precio', 'precio_descuento','duracion_dias_alquiler')


class SerializerLicencesName(serializers.ModelSerializer):
    desc_licence = serializers.CharField(source='licencia.descripcion', read_only=True)
    type_account = serializers.SerializerMethodField()

    class Meta:
        model = GameDetail
        fields = ('licencia', 'desc_licence', 'stock','type_account')

    def get_type_account(self, obj):
        licence_value = obj.licencia.id_license
        return 2 if licence_value == 3 else 1


class SerializerPriceSuscriptionProduct(serializers.ModelSerializer):
    class Meta:
        model = PriceForSuscription
        fields = ('tiempo_alquiler', 'precio')


class SerializerDaysForRentail(serializers.ModelSerializer):
    class Meta:
        model = DaysForRentail
        fields = ('pk', 'numero_dias', 'porcentaje_descuento')


class SerializerSales(serializers.ModelSerializer):
    cuenta = serializers.CharField(source='cuenta.cuenta', read_only=True)
    password = serializers.CharField(source='cuenta.password', read_only=True)
    productName = serializers.CharField(source='producto.title', read_only=True)
    productImage = serializers.CharField(source='producto.image', read_only=True)
    license = serializers.CharField(source='combinacion.licencia', read_only=True)
    console = serializers.CharField(source='combinacion.consola.descripcion', read_only=True)

    class Meta:
        model = SaleDetail
        fields = ('producto', 'cuenta', 'productName', 'productImage', 'password',
                  'fecha_venta', 'fecha_vencimiento', 'license', 'console')
