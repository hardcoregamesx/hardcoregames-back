# -*- coding: utf-8 -*-
"""Crea los permisos de Django para la app radar.

Django crea los permisos (`ver`, `agregar`, `cambiar`, `eliminar`) y los tipos
de contenido en el paso `migrate`. Este proyecto nunca corre `migrate` -- no
puede, ver docs/radar-ofertas.md -- asi que esos permisos no existen y no se le
pueden asignar a nadie.

El sintoma es confuso: un usuario de staff que entra a /admin/radar/... no ve
"no autorizado" sino **404**, porque Django oculta por completo las apps que el
usuario no puede ver. Parece que el despliegue fallo cuando en realidad esta
bien.

Un superusuario no lo necesita: se salta la comprobacion de permisos. Esto hace
falta solo para dar acceso a usuarios de staff.

    docker exec hc-django python manage.py radar_permisos
"""
from django.apps import apps
from django.contrib.auth.management import create_permissions
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Crea los tipos de contenido y permisos de la app radar, que normalmente crearia '
        '`migrate`. Sin ellos, un usuario de staff ve 404 en las pantallas del radar.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--app', default='radar',
            help='App para la que crear los permisos (default: radar).',
        )
        parser.add_argument(
            '--usuario', default=None,
            help='Correo o nombre de un usuario de staff al que darle todos estos permisos.',
        )

    def handle(self, *args, **options):
        nombre_app = options['app']
        try:
            config = apps.get_app_config(nombre_app)
        except LookupError:
            self.stderr.write(self.style.ERROR('No existe la app "%s".' % nombre_app))
            raise SystemExit(2)

        antes = Permission.objects.filter(content_type__app_label=nombre_app).count()
        create_permissions(config, verbosity=0)
        permisos = Permission.objects.filter(content_type__app_label=nombre_app)
        creados = permisos.count() - antes

        self.stdout.write('Permisos de "%s": %s en total (%s nuevos)' % (
            nombre_app, permisos.count(), creados))
        for p in permisos.order_by('content_type__model', 'codename'):
            self.stdout.write('  %s' % p.codename)

        identificador = options['usuario']
        if not identificador:
            self.stdout.write('')
            self.stdout.write(
                'Para darselos a alguien: manage.py radar_permisos --usuario <correo>')
            return

        from django.contrib.auth.models import User
        usuario = (User.objects.filter(email__iexact=identificador).first()
                   or User.objects.filter(username__iexact=identificador).first())
        if usuario is None:
            self.stderr.write(self.style.ERROR('No se encontro el usuario "%s".' % identificador))
            raise SystemExit(1)

        if usuario.is_superuser:
            self.stdout.write(
                '%s es superusuario: ya ve todo sin necesidad de permisos.' % identificador)
            return

        usuario.user_permissions.add(*permisos)
        if not usuario.is_staff:
            usuario.is_staff = True
            usuario.save(update_fields=['is_staff'])
            self.stdout.write('Se marco a %s como staff para que pueda entrar al admin.' % identificador)
        self.stdout.write(self.style.SUCCESS(
            '%s permisos asignados a %s.' % (permisos.count(), identificador)))
