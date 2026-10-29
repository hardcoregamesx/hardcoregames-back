"""Endpoints de Beneficios aliados. Autenticacion: el mismo Bearer JWT que ya
usa el frontend (ver views._get_verified_jwt_user).

Lanzamiento por etapas: mientras ALIANZAS_ABIERTO no sea "1" en el entorno,
solo los superusuarios reciben datos; el resto ve `habilitado: false`.
"""
import os

from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from products import alianzas, views
from products.models import Aliado, AliadoApertura


def _usuario_autorizado(request):
    """Devuelve (user, error_response, habilitado)."""
    user_id, is_superuser = views._get_verified_jwt_user(request)
    if user_id is None:
        return None, JsonResponse({"error": "No autenticado"}, status=401), False
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return None, JsonResponse({"error": "No autenticado"}, status=401), False
    habilitado = is_superuser or os.environ.get("ALIANZAS_ABIERTO") == "1"
    return user, None, habilitado


def beneficios_aliados(request):
    if request.method != "GET":
        return JsonResponse({"error": "Metodo no permitido"}, status=405)
    user, error, habilitado = _usuario_autorizado(request)
    if error:
        return error
    if not habilitado:
        return JsonResponse({"habilitado": False, "beneficios": []})
    return JsonResponse({"habilitado": True, "beneficios": alianzas.beneficios_para(user)})


@csrf_exempt
def apertura_aliado(request, aliado_id):
    """Registra que un cliente desbloqueado abrio la tarjeta de un aliado."""
    if request.method != "POST":
        return JsonResponse({"error": "Metodo no permitido"}, status=405)
    user, error, habilitado = _usuario_autorizado(request)
    if error:
        return error
    aliado = Aliado.objects.filter(pk=aliado_id, activo=True).first()
    if not habilitado or aliado is None or not alianzas.usuario_desbloqueado(user):
        return JsonResponse({"ok": False})
    AliadoApertura.objects.create(aliado=aliado, user=user, mes=alianzas.hoy_colombia().replace(day=1))
    return JsonResponse({"ok": True})
