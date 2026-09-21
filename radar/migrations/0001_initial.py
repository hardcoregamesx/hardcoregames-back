# -*- coding: utf-8 -*-
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='EjecucionRadar',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tienda', models.CharField(choices=[('XBOX', 'Xbox'), ('PS', 'PlayStation')], max_length=8)),
                ('regiones', models.CharField(blank=True, default='', max_length=120)),
                ('inicio', models.DateTimeField(auto_now_add=True)),
                ('fin', models.DateTimeField(blank=True, null=True)),
                ('ok', models.BooleanField(default=False)),
                ('juegos_vistos', models.IntegerField(default=0)),
                ('precios_guardados', models.IntegerField(default=0)),
                ('error', models.TextField(blank=True, default='')),
            ],
            options={
                'verbose_name': 'una ejecucion del radar',
                'verbose_name_plural': 'Ejecuciones del radar',
                'ordering': ['-inicio'],
            },
        ),
        migrations.CreateModel(
            name='JuegoDetectado',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tienda', models.CharField(choices=[('XBOX', 'Xbox'), ('PS', 'PlayStation')], max_length=8)),
                ('id_externo', models.CharField(help_text='bigId en Xbox; concept id en PlayStation.', max_length=64)),
                ('titulo', models.CharField(max_length=300)),
                ('descripcion', models.TextField(blank=True, default='')),
                ('imagen', models.CharField(blank=True, default='', max_length=700)),
                ('generos', models.CharField(blank=True, default='', max_length=300)),
                ('clasificacion', models.CharField(blank=True, default='', max_length=80)),
                ('plataformas', models.CharField(blank=True, default='', max_length=160)),
                ('desarrollador', models.CharField(blank=True, default='', max_length=200)),
                ('rating', models.FloatField(default=0)),
                ('rating_conteo', models.IntegerField(default=0)),
                ('precio_co', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('precio_co_oferta', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('comprable_co', models.BooleanField(default=True)),
                ('producto_existente_id', models.IntegerField(blank=True, null=True)),
                ('visto_primero', models.DateTimeField(auto_now_add=True)),
                ('visto_ultimo', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'un juego detectado',
                'verbose_name_plural': 'Juegos detectados',
                'ordering': ['titulo'],
                'unique_together': {('tienda', 'id_externo')},
            },
        ),
        migrations.CreateModel(
            name='ParametrosRadar',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('factor_precio_venta', models.DecimalField(
                    decimal_places=2, default=0.8,
                    help_text='El precio de venta se calcula como precio_colombia x este factor. 0.80 = el cliente ahorra 20%.',
                    max_digits=4)),
                ('margen_minimo_cop', models.BigIntegerField(
                    default=20000,
                    help_text='Ganancia minima en pesos para que una oferta se considere viable.')),
                ('descuento_minimo_pct', models.DecimalField(
                    decimal_places=2, default=10,
                    help_text='Descuento minimo en la tienda de origen para tener en cuenta la oferta.',
                    max_digits=5)),
                ('actualizado', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'parametros del radar',
                'verbose_name_plural': 'Parametros del radar',
            },
        ),
        migrations.CreateModel(
            name='TasaCambio',
            fields=[
                ('moneda', models.CharField(max_length=3, primary_key=True, serialize=False)),
                ('cop_por_unidad', models.DecimalField(decimal_places=6, max_digits=18)),
                ('manual', models.BooleanField(
                    default=False,
                    help_text='Si esta marcada, el actualizador automatico no la toca.')),
                ('nota', models.CharField(blank=True, default='', max_length=200)),
                ('actualizado', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'una tasa de cambio',
                'verbose_name_plural': 'Tasas de cambio',
                'ordering': ['moneda'],
            },
        ),
        migrations.CreateModel(
            name='PrecioRegional',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('region', models.CharField(max_length=2)),
                ('moneda', models.CharField(max_length=3)),
                ('precio_lista', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('precio_oferta', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('descuento_pct', models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ('comprable', models.BooleanField(default=False)),
                ('fecha_fin', models.DateTimeField(blank=True, help_text='Cuando vence la promocion.', null=True)),
                ('costo_cop', models.BigIntegerField(
                    blank=True, help_text='Precio de oferta convertido a pesos.', null=True)),
                ('actualizado', models.DateTimeField(auto_now=True)),
                ('juego', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='precios', to='radar.juegodetectado')),
            ],
            options={
                'verbose_name': 'un precio regional',
                'verbose_name_plural': 'Precios regionales',
                'ordering': ['region'],
                'unique_together': {('juego', 'region')},
            },
        ),
    ]
