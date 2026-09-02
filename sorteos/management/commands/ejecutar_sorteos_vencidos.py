from django.core.management.base import BaseCommand

from sorteos.services import STATUS_PARTICIPA, draw_winners, participation_rows, sorteos_vencidos_sin_cerrar


class Command(BaseCommand):
    help = (
        'Cierra automaticamente los sorteos en estado ACTIVE cuya end_date ya paso: '
        'elige ganador(es) al azar entre quienes califican y marca el sorteo FINISHED. '
        'Antes de este comando, "Ejecutar sorteo" era una accion manual del admin y un '
        'sorteo vencido se quedaba activo indefinidamente si nadie entraba a darle clic. '
        'Pensado para correr por cron cada 15 minutos (no hace nada si no hay sorteos '
        'vencidos, asi que es seguro correrlo seguido).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Muestra que sorteos se cerrarian y cuantos calificados hay, sin elegir ganador ni escribir nada.',
        )

    def handle(self, *args, **options):
        vencidos = list(sorteos_vencidos_sin_cerrar())

        if not vencidos:
            self.stdout.write('No hay sorteos vencidos por cerrar.')
            return

        if options['dry_run']:
            for sorteo in vencidos:
                calificados = sum(
                    1 for row in participation_rows(sorteo) if row['status'] == STATUS_PARTICIPA
                )
                self.stdout.write(
                    f'DRY RUN -- "{sorteo}" (id={sorteo.id}, vencio {sorteo.end_date.isoformat()}): '
                    f'{calificados} calificados, se elegirian {min(sorteo.winners_count, calificados)} ganador(es). '
                    f'No se escribio nada.'
                )
            return

        for sorteo in vencidos:
            chosen, calificados = draw_winners(sorteo)

            if not chosen:
                self.stdout.write(self.style.WARNING(
                    f'"{sorteo}" (id={sorteo.id}, vencio {sorteo.end_date.isoformat()}): '
                    f'nadie califica todavia, se deja ACTIVE para reintentar en el proximo cron.'
                ))
                continue

            self.stdout.write(self.style.SUCCESS(
                f'"{sorteo}" (id={sorteo.id}): {len(chosen)} ganador(es) elegido(s) entre '
                f'{calificados} calificados -- user_id(s) {chosen}. Sorteo marcado FINISHED.'
            ))
