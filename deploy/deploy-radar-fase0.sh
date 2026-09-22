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

# Comprobar POR NOMBRE que estan las tablas que el codigo necesita.
#
# Antes esto contaba tablas y exigia que fueran exactamente 5. Al agregar
# radar_tasatienda y radar_franquicia pasaron a ser 7, la igualdad dejo de
# cumplirse, y el script empezo a abortar antes de promover: un guardarraíl
# convertido en bloqueo, y encima con un mensaje que parecia un problema de la
# base de datos. Contar cosas que crecen es fragil; comprobar nombres no.
REQUERIDAS="radar_parametrosradar radar_tasacambio radar_juegodetectado radar_precioregional radar_ejecucionradar radar_tasatienda radar_franquicia radar_combo radar_combojuego"
FALTAN=""
for TABLA in $REQUERIDAS; do
  EXISTE=$(docker exec hc-postgres psql -U hardcoregames -d hardcoregames -tAc \
    "select count(*) from information_schema.tables where table_schema='public' and table_name='$TABLA'" | tr -d ' ')
  [ "$EXISTE" = "1" ] || FALTAN="$FALTAN $TABLA"
done
if [ -n "$FALTAN" ]; then
  echo "ERROR: faltan tablas en la base:$FALTAN"
  echo "       El SQL de arriba no las creo. No se promueve nada."
  exit 1
fi
echo "   las tablas del radar existen"

echo "== 5/7 Promoviendo la imagen a produccion"
bash /root/deploy_hc.sh hc-django promote "$TAG"
docker ps --filter name=hc-django --format "   {{.Names}} {{.Status}}"

# Comprobacion de salud DESDE DENTRO del contenedor.
#
# Antes esto le pedia al host que abriera https://admin.hardcoregames.co. Mala
# idea: si el servidor no puede alcanzar su propio dominio publico -- cosa
# comun -- la comprobacion falla, el script cree que rompio el sitio y revierte
# un despliegue que estaba perfecto. El sintoma es desconcertante: el
# despliegue "corre bien" y sigue corriendo la imagen vieja.
#
# Ahora se comprueba lo que de verdad importa y no depende de la red externa:
# que el contenedor este arriba, que tenga el codigo nuevo y que su servidor
# responda en localhost.
echo "   comprobando el contenedor..."
SANO=1

if ! docker ps --filter name=hc-django --filter status=running --format '{{.Names}}' | grep -q hc-django; then
  echo "ERROR: el contenedor hc-django no quedo corriendo. Revirtiendo."
  bash /root/deploy_hc.sh hc-django rollback
  exit 1
fi

if docker exec hc-django test -f radar/tiendas/vouchers.py; then
  echo "   el codigo nuevo esta dentro de la imagen"
else
  echo "   AVISO: la imagen no trae radar/tiendas/vouchers.py. Revisa que el build"
  echo "          haya usado el checkout actualizado."
  SANO=0
fi

RESPUESTA=$(docker exec hc-django python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/admin/login/', timeout=15).status)" 2>/dev/null || echo 000)
case "$RESPUESTA" in
  200|301|302) echo "   el servidor responde dentro del contenedor ($RESPUESTA)" ;;
  *)
    echo "ERROR: el servidor no responde dentro del contenedor (codigo: $RESPUESTA). Revirtiendo."
    bash /root/deploy_hc.sh hc-django rollback
    exit 1
    ;;
esac

if [ "$SANO" -ne 1 ]; then
  echo "   El despliegue sigue en pie, pero revisa el aviso de arriba."
fi

echo "== 6/7 Permisos, tasas y primera corrida del radar"
# Los permisos del admin normalmente los crea `migrate`, que aqui no se puede
# correr. Sin ellos un usuario de staff ve 404 en las pantallas del radar.
docker exec hc-django python manage.py radar_permisos || echo "   AVISO: no se pudieron crear los permisos del radar"

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

# Cada linea se comprueba por separado. Antes bastaba con que existiera
# `radar_xbox` para dar el cron por instalado, asi que las tareas que se
# agregaron despues nunca llegaron a programarse -- y `radar_vencer` es la que
# baja de la tienda las promociones que ya terminaron. Sin ella, un juego
# desaparece de la landing pero sigue comprable por enlace directo, al precio
# de una promocion que ya no existe: cada una de esas ventas es a perdida.
NUEVAS=$(mktemp)
cp "$RESPALDO" "$NUEVAS"
agregar() {
  if ! grep -q "$1" "$NUEVAS"; then
    echo "$2" >> "$NUEVAS"
    echo "   + $1"
  fi
}
grep -q 'Radar de ofertas' "$NUEVAS" || \
  echo "# Radar de ofertas (docs/radar-ofertas.md). Las tasas van antes que el radar." >> "$NUEVAS"

agregar 'radar_tasas'  "0 6 * * *    docker exec hc-django python manage.py radar_tasas   >> $LOG 2>&1"
agregar 'radar_xbox'   "15 6 * * *   docker exec hc-django python manage.py radar_xbox    >> $LOG 2>&1"
# Cada media hora: una promocion puede vencer a cualquier hora del dia.
agregar 'radar_playstation' "40 6 * * *   docker exec hc-django python manage.py radar_playstation >> $LOG 2>&1"
# Los combos se proponen despues de los dos radares: necesitan las ofertas del
# dia ya guardadas. Son borradores sin precio, no publican nada.
agregar 'radar_combos' "50 6 * * *   docker exec hc-django python manage.py radar_combos    >> $LOG 2>&1"
agregar 'radar_vencer' "*/30 * * * * docker exec hc-django python manage.py radar_vencer  >> $LOG 2>&1"
# Una vez al dia basta para borrar lo que vencio sin venderse.
agregar 'radar_limpiar' "30 5 * * *  docker exec hc-django python manage.py radar_limpiar >> $LOG 2>&1"

if cmp -s "$RESPALDO" "$NUEVAS"; then
  echo "   el cron ya estaba completo"
else
  crontab "$NUEVAS"
  DESPUES=$(crontab -l | grep -cve '^[[:space:]]*$' || true)
  if [ "$DESPUES" -lt "$ANTES" ]; then
    echo "ERROR: el crontab quedo con menos lineas que antes ($DESPUES < $ANTES). Restaurando."
    crontab "$RESPALDO"
    exit 1
  fi
  echo "   cron actualizado ($ANTES -> $DESPUES lineas)"
fi
rm -f "$NUEVAS"
crontab -l | grep 'radar_' || true

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
