from django.contrib.auth.models import User
from django.db import models


class User_Customized(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone_number = models.CharField(max_length=20)
    avatar = models.CharField(max_length=500, default="")
    puntos = models.IntegerField(default=0)
    is_guest_account = models.BooleanField(default=False)