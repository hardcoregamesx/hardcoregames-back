"""Sincroniza al catálogo de Ventas los juegos que se crean/editan en este admin.

Al guardar una combinación (GameDetail) se avisa a hardcoregames-ventas, que
crea el producto/variante si falta (con costo pendiente). Best effort: si Ventas
no responde NO se rompe el guardado del admin; solo se registra el error.
Reenviar es idempotente, así que re-guardar el juego repara cualquier fallo.
"""

import logging
import os
import threading

import requests
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

URL = os.getenv("VENTAS_CATALOGO_WEBHOOK_URL", "https://ventas.srv936408.hstgr.cloud/webhooks/catalogo/")
SECRET = os.getenv("VENTAS_PLANES_WEBHOOK_SECRET", "")
TIPO_VIDEOJUEGO = 1
_lock = threading.Lock()


def enviar_producto(producto_id):
    from products.models import GameDetail, Products

    producto = Products.objects.filter(pk=producto_id).first()
    if not producto or producto.type_id_id != TIPO_VIDEOJUEGO:
        return None
    combos = [
        {"licencia": g.licencia.descripcion, "consola": g.consola.descripcion}
        for g in GameDetail.objects.filter(producto=producto).select_related("licencia", "consola")
        if g.licencia and g.consola
    ]
    if not combos:
        return None
    with _lock:
        r = requests.post(
            URL,
            json={"titulo": producto.title, "combinaciones": combos},
            headers={"X-Planes-Token": SECRET},
            timeout=15,
        )
    if r.status_code != 200:
        logger.error("Sync Ventas fallo (%s) producto %s: %s", r.status_code, producto_id, r.text[:300])
    return r


def _enviar_seguro(producto_id):
    try:
        enviar_producto(producto_id)
    except Exception:
        logger.exception("Sync Ventas: no se pudo avisar de producto %s", producto_id)


def _al_guardar(sender, instance, **kwargs):
    if not SECRET or not instance.producto_id:
        return
    pid = instance.producto_id
    transaction.on_commit(lambda: threading.Thread(target=_enviar_seguro, args=(pid,), daemon=True).start())


def registrar():
    from products.models import GameDetail

    post_save.connect(_al_guardar, sender=GameDetail, dispatch_uid="ventas_sync_gamedetail")
