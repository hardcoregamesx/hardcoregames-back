from django.contrib.auth.models import User
from django.db import models


class User_Customized(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone_number = models.CharField(max_length=20)
    avatar = models.CharField(max_length=500, default="")
    puntos = models.IntegerField(default=0)
    is_guest_account = models.BooleanField(default=False)
    # Origen de adquisición (first-touch), capturado por el frontend en la
    # primera visita y enviado recién al registrarse. Ver "De dónde vienen
    # los clientes" (handoff 16/09/2026). Vacío/blank para las cuentas
    # creadas antes de este cambio: el CRM las muestra como "desconocido",
    # nunca como un cero que engañe.
    origen = models.CharField(max_length=100, blank=True, default="")
    origen_medio = models.CharField(max_length=100, blank=True, default="")
    origen_campana = models.CharField(max_length=200, blank=True, default="")
    origen_referrer = models.CharField(max_length=200, blank=True, default="")
    origen_fecha = models.DateTimeField(null=True, blank=True)