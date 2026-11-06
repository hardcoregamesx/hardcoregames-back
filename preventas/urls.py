from django.urls import path

from . import views

urlpatterns = [
    path('list/', views.preventas_list, name='preventas_list'),
    path('detail/', views.preventa_detail, name='preventa_detail'),
    path('reservar/', views.reservar, name='preventas_reservar'),
    path('consulta/', views.consulta, name='preventas_consulta'),
    path('pagarSaldo/', views.pagar_saldo, name='preventas_pagar_saldo'),
    path('pagarAbono/', views.pagar_abono, name='preventas_pagar_abono'),
    path('yaTransferi/', views.ya_transferi, name='preventas_ya_transferi'),
]
