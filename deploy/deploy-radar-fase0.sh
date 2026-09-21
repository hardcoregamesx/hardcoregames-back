#!/bin/bash
# Despliegue de la fase 0 del radar de ofertas (spec: docs/radar-ofertas.md).
#
# Ejecutar en el VPS como root:
#   git -C /opt/hardcoregames/repos/django pull --ff-only
#   bash /opt/hardcoregames/repos/django/deploy/deploy-radar-fase0.sh
#
# Es idempotente: se puede volver a correr sin romper nada.
#
# La fase 0 NO publica nada ni toca el catalogo. Solo crea tablas nuevas de una
# app nueva y agrega dos lineas de cron. Si algo sale mal, `rollback` devuelve la
# imagen anterior y las tablas quedan vacias sin estorbar a nadie.
set -e
cd /root

REPO=/opt/hardcoregames/repos/django
TAG=candidate-radar

echo "== 1/7 Verificando que el checkout tenga el radar"
test -f "$REPO/radar/management/commands/radar_xbox.py" \
  || { echo "ERROR: el checkout no tiene la app radar. Falta 'git pull'."; exit 1; }
git -C "$REPO" log --oneline -1

echo "== 2/7 Construyendo imagen hc-django:$TAG"
docker build -t "hc-django:$TAG" "$REPO"

echo "== 3/7 Probando la imagen en un contenedor desechable (sin etiquetas de Traefik)"
docker rm -f hc-django-test-radar >/dev/null 2>&1 || true
docker run --rm --network hc-net --env-file /root/hc/hc-django.env \
  "hc-django:$TAG" python manage.py check
echo "   check OK"

echo "== 4/7 Aplicando la migracion de la app radar"
# SOLO la app radar: `products` no tiene migraciones y un `migrate` a secas
# intentaria cosas que no debe (ver docs/radar-ofertas.md).
docker run --rm --network hc-net --env-file /root/hc/hc-django.env \
  "hc-django:$TAG" python manage.py migrate radar
docker exec hc-postgres psql -U hardcoregames -d hardcoregames -tAc \
  "select count(*) from information_schema.tables where table_name like 'radar_%'" \
  | tr -d ' '

echo "== 5/7 Promoviendo la imagen a produccion"
bash /root/deploy_hc.sh hc-django promote "$TAG"
docker ps --filter name=hc-django --format "   {{.Names}} {{.Status}}"

echo "== 6/7 Sembrando tasas de cambio y primera corrida del radar"
docker exec hc-django python manage.py radar_tasas
docker exec hc-django python manage.py radar_xbox
docker exec hc-django python manage.py radar_reporte --top 15 --min-resenas 20

echo "== 7/7 Instalando el cron diario (idempotente)"
LOG=/opt/hardcoregames/radar.log
if crontab -l 2>/dev/null | grep -q 'radar_xbox'; then
  echo "   el cron del radar ya existia, no se toca"
else
  ( crontab -l 2>/dev/null
    echo "# Radar de ofertas (docs/radar-ofertas.md). Las tasas van antes que el radar."
    echo "0 6 * * *  docker exec hc-django python manage.py radar_tasas >> $LOG 2>&1"
    echo "15 6 * * * docker exec hc-django python manage.py radar_xbox  >> $LOG 2>&1"
  ) | crontab -
  echo "   cron instalado"
fi
crontab -l | grep -A1 'Radar de ofertas' || true

echo
echo "Listo. La fase 0 esta corriendo."
echo
echo "SIGUIENTE PASO MANUAL, y es importante:"
echo "  En el admin -> Radar de ofertas -> Tasas de cambio, editar la fila USD"
echo "  con el costo REAL de conseguir el dolar. Viene sembrada con la TRM"
echo "  oficial, que es mas alta que lo que se paga, asi que hasta que se edite"
echo "  los margenes de USA se van a ver peores de lo que son."
echo
echo "  Rollback si hiciera falta:  bash /root/deploy_hc.sh hc-django rollback"
