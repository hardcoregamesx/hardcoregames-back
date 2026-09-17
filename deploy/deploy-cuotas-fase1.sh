#!/bin/bash
# Despliegue fase 1 de cuotas y reserva (spec: docs/cuotas-y-reserva.md §8).
# Orden obligatorio: SQL -> FastAPI -> Django -> frontend-v2 -> ventas.
# Ejecutar en el VPS como root:
#   git -C /opt/hardcoregames/repos/django pull --ff-only
#   bash /opt/hardcoregames/repos/django/deploy/deploy-cuotas-fase1.sh
# Requiere que existan las imagenes *:candidate-cuotas (construidas el 17/09/2026).
set -e
cd /root

echo "== 1/6 SQL aditivo en hc-postgres (idempotente)"
docker exec -i hc-postgres psql -U hardcoregames -d hardcoregames -v ON_ERROR_STOP=1 \
  < /opt/hardcoregames/repos/django/products/sql/2026-09-cuotas-reserva.sql
docker exec hc-postgres psql -U hardcoregames -d hardcoregames -tAc \
  "select count(*) from information_schema.columns where table_name='products_gamedetail' and column_name in ('cuotas_activas','num_cuotas','valor_cuota','cuota_inicial','reserva_activa','monto_reserva')" \
  | grep -qx 6 && echo "   columnas OK"

echo "== 2/6 Variables de entorno (secreto compartido tienda <-> ventas)"
if ! grep -q '^VENTAS_PLANES_WEBHOOK_SECRET=' /root/hc/hc-django.env; then
  SECRET=$(openssl rand -hex 32)
  printf '\nVENTAS_PLANES_WEBHOOK_URL=https://ventas.srv936408.hstgr.cloud/webhooks/planes/\nVENTAS_PLANES_WEBHOOK_SECRET=%s\n' "$SECRET" >> /root/hc/hc-django.env
  printf '\nPLANES_WEBHOOK_SECRET=%s\nPLANES_SYSTEM_USERNAME=web\n' "$SECRET" >> /root/hc-ventas/hc-ventas-django.env
  echo "   secreto generado y escrito en ambos .env"
else
  echo "   ya existian, no se tocan"
fi

echo "== 3/6 FastAPI"
bash /root/deploy_hc.sh hc-fastapi promote candidate-cuotas
echo "== 4/6 Django"
bash /root/deploy_hc.sh hc-django promote candidate-cuotas
echo "== 5/6 frontend-v2"
bash /root/deploy_hc.sh hc-frontend-v2 promote candidate-cuotas
echo "== 6/6 ventas (corre migrate al arrancar; respaldo previo de su base)"
mkdir -p /root/backups
docker exec hc-ventas-postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > /root/backups/ventas-pre-cuotas-$(date +%Y%m%d-%H%M%S).sql
bash /root/deploy_hc.sh hc-ventas-django promote candidate-cuotas

echo "== Verificacion"
sleep 8
curl -s 'https://api.hardcoregames.co/products/filter?console_id=2,1&limit=200' | grep -o 'id_product' | wc -l | sed 's/^/   productos en filter (esperado ~143): /'
curl -s 'https://api.hardcoregames.co/products/combination-price/258' | grep -o 'cuotas_activas' | head -1 | sed 's/^/   combination-price expone: /'
curl -s -o /dev/null -w '   admin login: %{http_code}\n' -L https://admin.hardcoregames.co/admin/login/
curl -s -D - -o /dev/null -m 12 https://www.hardcoregames.co/ | grep -i x-powered-by | sed 's/^/   www: /'
curl -s -o /dev/null -w '   /pagos: %{http_code}\n' -m 12 https://www.hardcoregames.co/pagos
curl -s -o /dev/null -w '   ventas webhook sin token (esperado 403): %{http_code}\n' -X POST https://ventas.srv936408.hstgr.cloud/webhooks/planes/ -H 'Content-Type: application/json' -d '{}'
curl -s http://172.20.0.4:8080/api/http/services/hcapi@docker | tr ',' '\n' | grep -i url | sed 's/^/   traefik hcapi: /'
echo "== Listo. Rollback por servicio: bash /root/deploy_hc.sh <svc> rollback"
