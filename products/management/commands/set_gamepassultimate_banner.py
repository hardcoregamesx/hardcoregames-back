import json

from django.core.management.base import BaseCommand, CommandError

from products.models import VariablesSistema

VARIABLE_NAME = 'gamepassultimate'
DEFAULT_IMAGE = (
    'https://cms-assets.xboxservices.com/assets/35/4b/'
    '354b3ddf-1b39-48c2-92d7-44e5fda75dc4.jpg?n=RE2TAjc.jpg&q=90&o=f'
)


class Command(BaseCommand):
    help = (
        'Fija banner_image dentro del JSON de la variable de sistema '
        '"gamepassultimate", sin tocar ningún otro campo (respeta ediciones '
        'ya hechas a mano en el admin, como los textos de trust). Sin '
        'argumento usa la imagen oficial de Game Pass Ultimate que ya se '
        'usa en el catálogo.'
    )

    def add_arguments(self, parser):
        parser.add_argument('image_url', nargs='?', default=DEFAULT_IMAGE)

    def handle(self, *args, **options):
        row = VariablesSistema.objects.filter(nombre_variable=VARIABLE_NAME).first()
        if not row:
            raise CommandError(
                f'No existe la variable "{VARIABLE_NAME}". Corre '
                'seed_gamepassultimate_variable primero.'
            )

        data = json.loads(row.valor)
        data[VARIABLE_NAME]['banner_image'] = options['image_url']
        row.valor = json.dumps(data, ensure_ascii=False, indent=3)
        row.save(update_fields=['valor'])

        self.stdout.write(self.style.SUCCESS(
            f'banner_image actualizado (el resto del JSON queda intacto).'
        ))
