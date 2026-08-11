from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from users.models import User_Customized


# ------------------------------------------------------------------ #
#  Inline: edita phone, avatar y puntos desde el detalle del usuario  #
# ------------------------------------------------------------------ #

class UserCustomizedInline(admin.StackedInline):
    model = User_Customized
    can_delete = False
    verbose_name_plural = 'Perfil personalizado'
    fields = ('phone_number', 'avatar', 'puntos')


# ------------------------------------------------------------------ #
#  UserAdmin: muestra teléfono y puntos en la lista; puntos editable  #
#  desde el detalle vía inline                                        #
# ------------------------------------------------------------------ #

class UserAdmin(BaseUserAdmin):
    inlines = (UserCustomizedInline,)
    list_display = ('username', 'email', 'first_name', 'last_name',
                    'get_phone', 'get_puntos')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user_customized')

    def get_phone(self, obj):
        try:
            return obj.user_customized.phone_number or '-'
        except User_Customized.DoesNotExist:
            return '-'
    get_phone.short_description = 'Teléfono'

    def get_puntos(self, obj):
        try:
            return obj.user_customized.puntos
        except User_Customized.DoesNotExist:
            return 0
    get_puntos.short_description = 'Puntos'


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
