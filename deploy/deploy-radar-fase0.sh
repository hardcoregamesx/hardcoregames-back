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

echo "== 4/7 Creando las tablas del radar (SQL aditivo, idempotente)"
# Este proyecto NO usa `migrate` en ningun app: el `users` declara una relacion
# hacia auth.User sin tener migraciones propias, asi que Django se niega a
# construir el grafo. El esquema se crea con SQL directo, igual que en
# products/sql y membership/sql. Ver docs/radar-ofertas.md.
docker exec -i hc-postgres psql -U hardcoregames -d hardcoregames -v ON_ERROR_STOP=1 \
  < "$REPO/radar/sql/2026-09-radar.sql"

TABLAS=$(docker exec hc-postgres psql -U hardcoregames -d hardcoregames -tAc \
  "select count(*) from information_schema.tables where table_name like 'radar\\_%'" | tr -d ' ')
if [ "$TABLAS" -ne 5 ]; then
  echo "ERROR: se esperaban 5 tablas radar_* y hay $TABLAS. No se promueve nada."
  exit 1
fi
echo "   las 5 tablas radar_* existen"

echo "== 5/7 Promoviendo la imagen a produccion"
bash /root/deploy_hc.sh hc-django promote "$TAG"
docker ps --filter name=hc-django --format "   {{.Names}} {{.Status}}"

# Comprobar que el admin siga en pie. Si la herramienta de chequeo no esta
# disponible se avisa y se sigue: no tiene sentido revertir un despliegue sano
# solo porque falta `curl` en el host.
if command -v curl >/dev/null 2>&1; then
  echo "   comprobando que el admin siga respondiendo..."
  OK=0
  for i in $(seq 1 20); do
    CODIGO=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
      https://admin.hardcoregames.co/admin/login/ || echo 000)
    case "$CODIGO" in
      200|301|302) OK=1; echo "   admin responde ($CODIGO)"; break ;;
    esac
    sleep 3
  done
  if [ "$OK" -ne 1 ]; then
    echo "ERROR: el admin no responde tras un minuto (ultimo codigo: $CODIGO). Revirtiendo."
    bash /root/deploy_hc.sh hc-django rollback
    exit 1
  fi
else
  echo "   AVISO: no hay curl en el host, no se pudo comprobar el admin."
  echo "          Abre https://admin.hardcoregames.co/admin/ y confirma que carga."
fi

echo "== 6/7 Sembrando tasas de cambio y primera corrida del radar"
# A esta altura la imagen ya esta promovida y el despliegue es un exito. Que la
# primera corrida del radar tropiece con un corte de red no es motivo para
# abortar: el cron la repite manana, y se puede relanzar a mano. Por eso estos
# pasos no llevan `set -e`.
docker exec hc-django python manage.py radar_tasas || echo "   AVISO: fallaron las tasas; relanza: docker exec hc-django python manage.py radar_tasas"
if docker exec hc-django python manage.py radar_xbox; then
  docker exec hc-django python manage.py radar_reporte --top 15 --min-resenas 20 || true
else
  echo "   AVISO: la primera corrida del radar no termino. El despliegue SI quedo bien."
  echo "          Relanzala con: docker exec hc-django python manage.py radar_xbox"
fi

echo "== 7/7 Instalando el cron diario (idempotente)"
LOG=/opt/hardcoregames/radar.log
RESPALDO=/root/crontab-antes-de-radar-$(date +%Y%m%d-%H%M%S).txt

# El crontab de este servidor tiene los chequeos de pagos, los backups y los
# sorteos. Reescribirlo mal los borra en silencio, asi que aqui no se toca nada
# sin haberlo respaldado y sin que el contenido tenga sentido.
if ! crontab -l > "$RESPALDO" 2>/dev/null; then
  echo "ERROR: no se pudo leer el crontab actual. No se toca nada."
  echo "       Agrega estas dos lineas a mano con 'crontab -e':"
  echo "       0 6 * * *  docker exec hc-django python manage.py radar_tasas >> $LOG 2>&1"
  echo "       15 6 * * * docker exec hc-django python manage.py radar_xbox  >> $LOG 2>&1"
  exit 1
fi

ANTES=$(grep -cve '^[[:space:]]*$' "$RESPALDO" || true)
if [ "$ANTES" -lt 5 ]; then
  echo "ERROR: el crontab actual tiene solo $ANTES lineas utiles y se esperaban muchas mas."
  echo "       Algo no cuadra; no se reescribe. Respaldo en $RESPALDO"
  exit 1
fi
echo "   crontab respaldado en $RESPALDO ($ANTES lineas)"

if grep -q 'radar_xbox' "$RESPALDO"; then
  echo "   el cron del radar ya existia, no se toca"
else
  {
    cat "$RESPALDO"
    echo "# Radar de ofertas (docs/radar-ofertas.md). Las tasas van antes que el radar."
    echo "0 6 * * *  docker exec hc-django python manage.py radar_tasas >> $LOG 2>&1"
    echo "15 6 * * * docker exec hc-django python manage.py radar_xbox  >> $LOG 2>&1"
  } | crontab -

  DESPUES=$(crontab -l | grep -cve '^[[:space:]]*$' || true)
  if [ "$DESPUES" -lt "$ANTES" ]; then
    echo "ERROR: el crontab quedo con menos lineas que antes ($DESPUES < $ANTES). Restaurando."
    crontab "$RESPALDO"
    exit 1
  fi
  echo "   cron instalado ($ANTES -> $DESPUES lineas)"
fi
crontab -l | grep -A2 'Radar de ofertas' || true

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
