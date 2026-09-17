from datetime import date

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
        fields = ('producto', 'licencia', 'precio', 'precio_descuento', 'duracion_dias_alquiler',
                  'cuotas_activas', 'num_cuotas', 'valor_cuota', 'cuota_inicial',
                  'reserva_activa', 'monto_reserva')

    def clean(self):
        """Ver docs/cuotas-y-reserva.md §4.2: cuotas_activas exige
        valor_cuota > 0, num_cuotas >= 2 y licencia Primaria/Secundaria (id 1
        o 2); reserva_activa exige monto_reserva > 0 y que el producto tenga
        fecha_lanzamiento futura."""
        cleaned_data = super().clean()
        producto = cleaned_data.get('producto')
        licencia = cleaned_data.get('licencia')

        if cleaned_data.get('cuotas_activas'):
            if not cleaned_data.get('valor_cuota'):
                self.add_error('valor_cuota', 'Cuotas activas exige un valor de cuota mayor a 0.')
            if (cleaned_data.get('num_cuotas') or 0) < 2:
                self.add_error('num_cuotas', 'Cuotas activas exige al menos 2 cuotas.')
            if licencia and licencia.id_license not in (1, 2):
                self.add_error('cuotas_activas', 'Cuotas solo aplica a licencia Primaria o Secundaria.')

        if cleaned_data.get('reserva_activa'):
            if not cleaned_data.get('monto_reserva'):
                self.add_error('monto_reserva', 'Reserva activa exige un monto de reserva mayor a 0.')
            fecha_lanzamiento = getattr(producto, 'fecha_lanzamiento', None)
            if not fecha_lanzamiento or fecha_lanzamiento <= date.today():
                self.add_error(
                    'reserva_activa',
                    'Reserva solo se puede activar si el producto tiene una fecha de lanzamiento futura.',
                )

        return cleaned_data