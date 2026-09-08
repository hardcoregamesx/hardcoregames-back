from django.contrib import admin

from .models import (
    GoogleOAuthCredential,
    MembershipDiscountLog,
    MembershipLevelMapping,
    MembershipPointsClaim,
    YoutubeMembershipLink,
)


@admin.register(YoutubeMembershipLink)
class YoutubeMembershipLinkAdmin(admin.ModelAdmin):
    list_display = ('user', 'youtube_channel_id', 'youtube_display_name', 'tier', 'status', 'linked_at', 'last_synced_at')
    list_filter = ('status', 'tier')
    search_fields = ('user__username', 'user__email', 'youtube_channel_id', 'youtube_display_name')

    def has_add_permission(self, request):
        # Se crea solo desde el flujo de conexion (OAuth), nunca a mano.
        return False


@admin.register(MembershipLevelMapping)
class MembershipLevelMappingAdmin(admin.ModelAdmin):
    list_display = ('google_level_name', 'tier')
    list_editable = ('tier',)


@admin.register(MembershipPointsClaim)
class MembershipPointsClaimAdmin(admin.ModelAdmin):
    list_display = ('user', 'week_start_date', 'points_awarded', 'claimed_at')
    list_filter = ('week_start_date',)
    search_fields = ('user__username', 'user__email')
    date_hierarchy = 'claimed_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MembershipDiscountLog)
class MembershipDiscountLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'transaction', 'tier', 'percent_applied', 'amount_saved', 'applied_at')
    list_filter = ('tier',)
    search_fields = ('user__username', 'user__email')
    date_hierarchy = 'applied_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(GoogleOAuthCredential)
class GoogleOAuthCredentialAdmin(admin.ModelAdmin):
    list_display = ('provider', 'access_token_expires_at', 'updated_at')

    def has_add_permission(self, request):
        # Solo debe existir la fila 'youtube_creator', creada una vez a mano
        # tras la captura del refresh token (Fase 0 del plan).
        return not GoogleOAuthCredential.objects.exists()
