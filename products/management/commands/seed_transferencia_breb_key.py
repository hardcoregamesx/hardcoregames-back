from django.core.management.base import BaseCommand

from products.models import VariablesSistema

VARIABLE_NAME = 'transferencia_breb_key'
DEFAULT_VALUE = '@nequimil688'


class Command(BaseCommand):
    help = (
        'Crea la variable de sistema "transferencia_breb_key" (la llave Bre-B que se '
        'muestra en el checkout para pagos por transferencia) si no existe todavía. '
        'Editarla desde el admin cambia la cuenta bancaria sin tocar código ni '
        'redesplegar. No sobrescribe si ya existe; usa --force para resetear.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Sobrescribe el valor aunque la variable ya exista.',
        )

    def handle(self, *args, **options):
        existing = VariablesSistema.objects.filter(nombre_variable=VARIABLE_NAME).first()

        if existing and not options['force']:
            self.stdout.write(
                f'La variable "{VARIABLE_NAME}" ya existe (id={existing.pk}, '
                f'valor="{existing.valor}"). No se modificó. Usa --force para resetearla.'
            )
            return

        obj, created = VariablesSistema.objects.update_or_create(
            nombre_variable=VARIABLE_NAME,
            defaults={
                'descripcion': (
                    'Llave Bre-B (Nequi/Davivienda) que ve el cliente al elegir "Transferir '
                    'por llaves (Bre-B)" en el checkout. Cambiarla aquí actualiza el checkout '
                    'de inmediato, sin redesplegar nada.'
                ),
                'valor': DEFAULT_VALUE,
                'url': '',
                'estado': True,
            },
        )

        action = 'Creada' if created else 'Actualizada (--force)'
        self.stdout.write(self.style.SUCCESS(f'{action} la variable "{VARIABLE_NAME}" (id={obj.pk}).'))
