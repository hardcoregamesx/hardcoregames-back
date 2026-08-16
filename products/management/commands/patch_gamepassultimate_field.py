import json

from django.core.management.base import BaseCommand, CommandError

from products.models import VariablesSistema

VARIABLE_NAME = 'gamepassultimate'


class Command(BaseCommand):
    help = (
        'Fija un campo de texto de primer nivel dentro del JSON de la '
        'variable de sistema "gamepassultimate" (ej: cta_label, hero_title), '
        'sin tocar ningún otro campo. Para campos anidados (trust, faq) usa '
        'el admin directamente.'
    )

    def add_arguments(self, parser):
        parser.add_argument('field')
        parser.add_argument('value')

    def handle(self, *args, **options):
        row = VariablesSistema.objects.filter(nombre_variable=VARIABLE_NAME).first()
        if not row:
            raise CommandError(f'No existe la variable "{VARIABLE_NAME}".')

        data = json.loads(row.valor)
        field = options['field']
        if field not in data[VARIABLE_NAME]:
            raise CommandError(f'"{field}" no existe en el JSON actual (revisa el nombre).')

        data[VARIABLE_NAME][field] = options['value']
        row.valor = json.dumps(data, ensure_ascii=False, indent=3)
        row.save(update_fields=['valor'])

        self.stdout.write(self.style.SUCCESS(f'{field} actualizado.'))
