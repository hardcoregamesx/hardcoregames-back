from django import forms
from products.models import GameDetail, Licenses  # Import Licenses model

class UpdateProductForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        product_id = instance.producto.id_product if instance and instance.producto else None
        license_id = instance.licencia.id_license if instance and instance.licencia else None

        if product_id:
            games_inventory = GameDetail.objects.filter(
                producto__id_product=product_id,
                licencia__id_license=license_id
            ).distinct('duracion_dias_alquiler')

            licencia_queryset = Licenses.objects.filter(
                id_license__in=[item.licencia.id_license for item in games_inventory]
            )

            initial_licencia = licencia_queryset.first() if licencia_queryset.exists() else None

            self.fields['licencia'] = forms.ModelChoiceField(
                queryset=licencia_queryset,
                widget=forms.Select,
                required=True,
                label="Licencia",
                initial=initial_licencia
            )

            self.fields['duracion_dias_alquiler'] = forms.IntegerField(
                min_value=0,
                required=True,
                label="Días de alquiler",
                help_text="0 = producto de venta permanente (no es alquiler). "
                          "Mayor a 0 = días de duración del alquiler.",
            )

    class Meta:
        model = GameDetail
        fields = ('producto', 'licencia', 'precio', 'precio_descuento', 'duracion_dias_alquiler')