import json

from django.core.management.base import BaseCommand

from products.models import VariablesSistema

VARIABLE_NAME = 'gamepassultimate'

DEFAULT_CONTENT = {
    'gamepassultimate': {
        'platform_label': 'Xbox Series / Xbox One',
        'title': 'Game Pass Ultimate',
        'subtitle': 'Acceso a más de 500 juegos + multijugador online.',
        'price_label': 'Desde',
        'price_amount': '$37.990',
        'price_unit': 'COP / mes',
        'cta_label': 'Comprar ahora',
        'banner_image': '',
        'trust': [
            {'title': 'Entrega hoy', 'desc': 'Correo y clave al instante', 'tone': 'primary'},
            {'title': 'Con garantía', 'desc': 'Reposición si el código falla', 'tone': 'accent'},
            {'title': 'Soporte real', 'desc': 'Por WhatsApp', 'tone': 'cta'},
        ],
        'step1_eyebrow': 'Paso 1',
        'step1_title': '¿Cómo la vas a usar?',
        'step1_body': 'Con esto sabemos qué plan te conviene — sin que tengas que leer la ficha técnica completa.',
        'choice_a_title': 'Solo yo, en mi consola',
        'choice_a_desc': 'Te damos correo y clave. Es la opción más económica.',
        'choice_b_title': 'Prefiero mi propia cuenta',
        'choice_b_desc': 'Instalamos el servicio directo en tu perfil de Xbox. Ideal si le prestas tu perfil a alguien más.',
        'step2_eyebrow': 'Paso 2',
        'step2_title': 'Elige la duración',
        'step2_body_personal': 'Correo y clave para tu propio perfil de Xbox. No se comparte con nadie más.',
        'step2_body_propia': 'Código sobre tu cuenta: no compartes nada, se activa directamente en tu perfil de Xbox.',
        'badge_recommended': 'Recomendado',
        'badge_best_price': 'Mejor precio',
        'pick_button_label': 'Elegir',
        'stock_suffix': 'en stock',
        'low_stock_threshold': 2,
        'faq_eyebrow': 'Antes de pagar',
        'faq_title': 'Lo que suele preguntarse',
        'faq': [
            {
                'q': '¿Cuál es la diferencia entre primaria, secundaria y código?',
                'a': 'Primaria y secundaria: te damos una cuenta con correo y clave, juegas con tu propio perfil dentro de ella. Código: lo canjeas directamente sobre tu cuenta de Xbox, sin compartir nada con nadie.',
            },
            {
                'q': '¿Necesito internet después de instalar?',
                'a': 'No, una vez activado puedes jugar sin conexión constante, salvo para el multijugador online.',
            },
            {
                'q': '¿Puedo reinstalar cuando quiera?',
                'a': 'Sí, en cualquiera de las modalidades puedes reinstalar el servicio las veces que necesites.',
            },
            {
                'q': '¿Cómo cuenta Xbox los meses?',
                'a': 'Xbox cuenta cada mes como 30 días exactos, sin importar si el mes calendario tiene 28, 30 o 31.',
            },
            {
                'q': '¿Qué pasa si el código o la cuenta falla?',
                'a': 'Tienes garantía: si algo no funciona, te lo reponemos. Escríbenos por WhatsApp y lo resolvemos.',
            },
        ],
        'portal_title': '¿Quieres ver todas las duraciones y la letra chica completa?',
        'portal_desc': 'La ficha técnica completa del producto, con todas las variantes y notas, sigue disponible.',
        'portal_link': 'Ver ficha completa ›',
        'portal_href': 'https://www.hardcoregames.co/product/4',
        'footer': 'Hardcore Games — todos los derechos reservados.',
    }
}


class Command(BaseCommand):
    help = (
        'Crea la variable de sistema "gamepassultimate" (todo el copy editable '
        'de la landing /gamepassultimate) con su texto por defecto, si no '
        'existe todavía. No toca ninguna otra variable ni tabla. Por defecto '
        'no sobrescribe si el dueño ya la editó a mano en el admin; usa '
        '--force para resetear al texto de fábrica.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Sobrescribe el valor aunque la variable ya exista.',
        )

    def handle(self, *args, **options):
        valor = json.dumps(DEFAULT_CONTENT, ensure_ascii=False, indent=3)
        descripcion = (
            'Todos los textos y precios editables de la landing '
            'www.hardcoregames.co/gamepassultimate. El campo "valor" es un '
            'JSON: edítalo con cuidado de no romper las comillas ni las comas. '
            'banner_image puede quedar vacío (usa el fondo morado/celeste por '
            'defecto) o llevar la URL de una imagen (como los demás '
            'image_banner_*).'
        )

        existing = VariablesSistema.objects.filter(nombre_variable=VARIABLE_NAME).first()

        if existing and not options['force']:
            self.stdout.write(
                f'La variable "{VARIABLE_NAME}" ya existe (id={existing.pk}). '
                'No se modificó. Usa --force para resetearla al texto de fábrica.'
            )
            return

        obj, created = VariablesSistema.objects.update_or_create(
            nombre_variable=VARIABLE_NAME,
            defaults={'descripcion': descripcion, 'valor': valor, 'url': '', 'estado': True},
        )

        action = 'Creada' if created else 'Actualizada (--force)'
        self.stdout.write(self.style.SUCCESS(f'{action} la variable "{VARIABLE_NAME}" (id={obj.pk}).'))
