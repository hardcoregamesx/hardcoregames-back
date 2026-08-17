import json
import uuid
import random

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core import serializers
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.views.decorators.csrf import csrf_exempt

from django.conf import settings
from users.models import User_Customized
from users.userSerializer import UserSerializer, UserResponseSerializer, UserCustomSerializer
from utils.SendEmail import SendEmail
from utils.getJsonFromRequest import GetJsonFromRequest
from utils.joinModels import JoinModels


def get_all_users(request):
    all_users = User.objects.all()
    response = serializers.serialize("json", all_users, fields=('id', 'username', 'first_name', 'last_name', 'email', 'is_active', 'is_staff', 'is_superuser', 'date_joined', 'last_login'))
    payload = {'message': 'proceso exitoso', 'response': json.loads(response), 'code': '00', 'status': 200}

    return HttpResponse(JsonResponse(payload), content_type='application/json')


@csrf_exempt
def get_user_by_email(request, self=None):
    if request.method == "POST":
        body = GetJsonFromRequest.__int__(self, request)
        email = body['email']
        user_selected = User.objects.filter(username=email)
        if user_selected.exists():
            user_customized_selected = User_Customized.objects.filter(user__username=email)
            models_joined = JoinModels.__int__(self, user_selected, user_customized_selected)
            payload = {"fields": models_joined, 'message': 'proceso exitoso', 'code': '00', 'status': 200}
            return HttpResponse(JsonResponse({'data': payload}), content_type='application/json')

        return HttpResponse(JsonResponse({'message': "usuario no existe", 'status': 200, 'code': '01'}),
                            content_type="application/json")


@csrf_exempt
def get_user_by_id(request, id_user, self=None):
    if request.method == "GET":
        id_user = id_user
        user_selected = User.objects.filter(id=id_user)
        if user_selected.exists():
            user_customized_selected = User_Customized.objects.filter(user_id=id_user)
            serializer = UserResponseSerializer(user_selected, many=True)
            serializer_user_custom = UserCustomSerializer(user_customized_selected, many=True)
            payload = {"fields": serializer.data[0], "other_fields": serializer_user_custom.data[0],
                       'message': 'proceso exitoso', 'code': '00', 'status': 200}
            return HttpResponse(JsonResponse({'data': payload}), content_type='application/json')

        return HttpResponse(JsonResponse({'data': {}, 'status': 200, 'code': '01', 'message': 'el usuario no existe'}),
                            content_type="application/json")


@login_required
def index(request):
    return HttpResponse(JsonResponse({'message': 'index'}), content_type="application/json")


@csrf_exempt
def register(request, self=None):
    if request.method == "POST":
        body = GetJsonFromRequest.__int__(self, request)
        first_name = body.get('first_name', '')
        last_name = body.get('last_name', '')
        email = body.get('email', '')
        password = body.get('password', '')
        phone_number = body.get('phone_number', '')
        avatar = body.get('avatar', '')
        guest_checkout = bool(body.get('guest_checkout', False))

        email = (email or '').strip()
        try:
            validate_email(email)
        except ValidationError:
            return HttpResponse(
                JsonResponse({'message': 'debes indicar un email valido', "status": 400, "code": "01"}),
                content_type="application/json", status=400)

        if not password or len(password) < 8:
            return HttpResponse(
                JsonResponse({'message': 'la contrasena debe tener al menos 8 caracteres', "status": 400, "code": "01"}),
                content_type="application/json", status=400)

        existing_user = User.objects.filter(username=email).first()
        if existing_user:
            existing_profile = User_Customized.objects.filter(user_id=existing_user.id).first()
            is_guest_account = bool(existing_profile and existing_profile.is_guest_account)

            if guest_checkout and is_guest_account:
                # Segunda compra como invitado con el mismo correo: se rota la
                # contraseña técnica (el cliente nunca la ve) para que el login
                # inmediato del checkout funcione, sin tocar nombre ni perfil.
                existing_user.set_password(password)
                existing_user.save()
                return HttpResponse(JsonResponse({'message': 'usuario registrado exitosamente', "status": 200,
                                                  "code": "00", "user_id": existing_user.id}),
                                    content_type="application/json")

            if (not guest_checkout) and is_guest_account:
                # Formulario real de registro sobre una cuenta creada por el
                # checkout de invitado: se "reclama" en vez de rechazar, pero
                # solo si el correo ya probó ser suyo (paso de verificación
                # por código, ver validate_email_token) en los últimos 30 min.
                if not cache.get(f"email_verified:{email}"):
                    return HttpResponse(
                        JsonResponse({'message': 'verifica tu correo primero', "status": 400, "code": "01"}),
                        content_type="application/json", status=400)
                existing_user.first_name = first_name
                existing_user.last_name = last_name
                existing_user.set_password(password)
                existing_user.save()
                if existing_profile:
                    existing_profile.is_guest_account = False
                    if phone_number:
                        existing_profile.phone_number = phone_number
                    existing_profile.save()
                cache.delete(f"email_verified:{email}")
                return HttpResponse(JsonResponse({'message': 'usuario registrado exitosamente', "status": 200,
                                                  "code": "00", "user_id": existing_user.id}),
                                    content_type="application/json")

            return HttpResponse(
                JsonResponse({'message': 'ya existe un usuario con este email', "status": 400, "code": "01"}),
                content_type="application/json", status=400)
        user = User.objects.create_user(
            first_name=first_name,
            last_name=last_name,
            username=email,
            email=email,
            password=password
        )

        user.save()
        last_user_id = User.objects.last().id
        user_customized = User_Customized(user_id=last_user_id,
                                          phone_number=phone_number,
                                          avatar=avatar,
                                          is_guest_account=guest_checkout
                                          )
        user_customized.save()
        return HttpResponse(JsonResponse({'message': 'usuario registrado exitosamente', "status": 200,
                                          "code": "00", "user_id": last_user_id}), content_type="application/json")


@csrf_exempt
def login_request(request, self=None):
    if request.method == "POST":
        body_unicode = request.body.decode('utf-8')
        body = json.loads(body_unicode)
        username = body['user']
        password = body['password']
        user = authenticate(username=username, password=password)
        if user is not None:
            login(request, user)
            user_loged = User.objects.filter(username=username)
            serializer = UserSerializer(user_loged, many=True)
            payload = {"fields": serializer.data[0], 'message': 'proceso exitoso', 'code': '00', 'status': 200}
            return HttpResponse(JsonResponse({'data': payload}), content_type='application/json')

        return HttpResponse(JsonResponse({'message': "usuario o contraseña incorrectos", 'status': 200, 'code': '01'}),
                            content_type="application/json")


@csrf_exempt
def logout_request(request):
    user_logout = logout(request)
    if user_logout is not None:
        return HttpResponse(JsonResponse({'message': 'usuario logout'}), content_type="application/json")
    return HttpResponse(JsonResponse({'message': 'no hay usuario', 'status': 200, 'code': '01'}),
                        content_type="application/json")


@csrf_exempt
def update_user(request, self=None):
    if request.method == "POST":
        body = GetJsonFromRequest.__int__(self, request)
        user_id = body['user_id']
        first_name = body['first_name']
        last_name = body['last_name']
        email = body['email']
        exist_user = User.objects.filter(pk=user_id).exists()
        if exist_user:
            User.objects.filter(pk=user_id).update(first_name=first_name,
                                                   last_name=last_name,
                                                   username=email,
                                                   email=email)
            return HttpResponse(
                JsonResponse({'message': 'datos actualizados exitosamente', "status": 200, "code": "00"}),
                content_type="application/json")

        return HttpResponse(JsonResponse({'message': 'usuario no existe', "status": 200, "code": "01"}),
                            content_type="application/json")


@csrf_exempt
def change_password(request, self=None):
    if request.method == "POST":
        body = GetJsonFromRequest.__int__(self, request)
        user_id = body['user_id']
        current_pass = body['current_pass']
        new_pass = body['new_pass']
        exist_user = User.objects.filter(pk=user_id).exists()
        if exist_user:
            user = User.objects.get(pk=user_id)
            is_pass = user.check_password(current_pass)
            if is_pass:
                user.set_password(new_pass)
                user.save()
                return HttpResponse(
                    JsonResponse({'message': 'datos actualizados exitosamente', "status": 200, "code": "00"}),
                    content_type="application/json")
            return HttpResponse(
                JsonResponse({'message': 'datos incorrectos', "status": 200, "code": "01"}),
                content_type="application/json")

        return HttpResponse(JsonResponse({'message': 'usuario no existe', "status": 200, "code": "01"}),
                            content_type="application/json")


@csrf_exempt
def token_pass(request, self=None):
    if request.method == "POST":
        body = GetJsonFromRequest.__int__(self, request)
        username = body['username']
        exist_user = User.objects.filter(username=username).exists()
        subject_email = settings.SUBJECT_EMAIL_FOR_TOKEN
        text_email = settings.EMAIL_FOR_TOKEN
        if exist_user:
            token = str(uuid.uuid4())[0:6]
            token_key = f"password_reset_token:{token}"
            user_key = f"password_reset_user:{username}"

            old_token = cache.get(user_key)
            if old_token:
                cache.delete(f"password_reset_token:{old_token}")

            timeout_seconds = 60
            cache.set(token_key, username, timeout=timeout_seconds)
            cache.set(user_key, token, timeout=timeout_seconds)

            text_email += "<center><b>" + token + "</b><center>"
            print(f"Token: {token}, Username: {username}")
            print(f"Token key: {cache.get(token_key)}, User key: {user_key}")
            SendEmail.__int__(self, text_email, subject_email, username)
            return HttpResponse(
                JsonResponse({'message': 'codigo enviado al correo', "status": 200, "code": "00"}),
                content_type="application/json")

        return HttpResponse(JsonResponse({'message': 'usuario no existe', "status": 200, "code": "01"}),
                            content_type="application/json")


@csrf_exempt
def set_password(request, self=None):
    if request.method == "POST":
        body = GetJsonFromRequest.__int__(self, request)
        username = body['username']
        new_pass = body['new_password']
        exist_user = User.objects.filter(username=username).exists()
        if exist_user:
            user = User.objects.get(username=username)
            user.set_password(new_pass)
            user.save()
            return HttpResponse(
                JsonResponse({'message': "constraseña actualizada exitosamente", "status": 200, "code": "00"}),
                content_type="application/json")
        return HttpResponse(JsonResponse({'message': 'usuario no existe', "status": 200, "code": "01"}),
                            content_type="application/json")


@csrf_exempt
def create_email_validation_token(request, self=None):
    if request.method == "POST":
        body = GetJsonFromRequest.__int__(self, request)
        username = body.get("username", body.get("email", ""))

        # No creamos token si ya existe un usuario con este email
        username = (username or '').strip()
        try:
            validate_email(username)
        except ValidationError:
            return HttpResponse(
                JsonResponse({'message': 'debes indicar un email valido', "status": 200, "code": "01"}),
                content_type="application/json")

        existing_user = User.objects.filter(username=username).first()
        if existing_user:
            existing_profile = User_Customized.objects.filter(user_id=existing_user.id).first()
            is_guest_account = bool(existing_profile and existing_profile.is_guest_account)
            # Una cuenta creada por el checkout de invitado no cuenta como
            # "ya registrado" para el formulario real: se deja seguir el
            # flujo de verificación normal, como si el correo fuera nuevo.
            if not is_guest_account:
                return HttpResponse(
                    JsonResponse({'message': 'ya existe un usuario con este email', "status": 200, "code": "01"}),
                    content_type="application/json")

        subject_email = settings.SUBJECT_EMAIL_FOR_CONFIRMATION
        text_email = settings.TEMPLATE_FOR_EMAIL_CONFIRMATION or ""

        # Token numérico de 6 dígitos
        token = f"{random.randint(0, 999999):06d}"
        token_key = f"email_validation_token:{token}"
        while cache.get(token_key) is not None:
            token = f"{random.randint(0, 999999):06d}"
            token_key = f"email_validation_token:{token}"

        user_key = f"email_validation_user:{username}"
        old_token = cache.get(user_key)
        if old_token:
            cache.delete(f"email_validation_token:{old_token}")

        timeout_seconds = 15 * 60
        cache.set(token_key, username, timeout=timeout_seconds)
        cache.set(user_key, token, timeout=timeout_seconds)

        text_email += "<center><b>" + token + "</b><center>"
        SendEmail.__int__(self, text_email, subject_email, username)

        return HttpResponse(
            JsonResponse({'message': 'codigo enviado al correo', "status": 200, "code": "00"}),
            content_type="application/json")


@csrf_exempt
def validate_email_token(request, self=None):
    if request.method == "POST":
        body = GetJsonFromRequest.__int__(self, request)
        username = body.get("username", body.get("email", ""))
        token = body["token"]
        token_reason = body.get("reason", "email_validation_token")  # Default reason if not provided

        token_key = f"{token_reason}:{token}"
        user_from_cache = cache.get(token_key)

        if user_from_cache is None or user_from_cache != username:
            return HttpResponse(
                JsonResponse({'message': 'token inválido', "status": 200, "code": "01"}),
                content_type="application/json")

        # Token válido: eliminarlo para que sea de un solo uso
        cache.delete(token_key)
        user_key = f"email_validation_user:{username}"
        cache.delete(user_key)

        # Marca corta de "este correo probó ser suyo" — la exige register()
        # para dejar reclamar una cuenta de checkout de invitado sobre este
        # email, evitando que alguien la tome solo con conocer el correo.
        cache.set(f"email_verified:{username}", True, timeout=1800)

        return HttpResponse(
            JsonResponse({'message': 'token válido', "status": 200, "code": "00"}),
            content_type="application/json")

