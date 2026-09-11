from django.urls import path
from users import views

urlpatterns = [
    path("", views.get_all_users, name=""),
    path("index/", views.index, name="index"),
    path("login/", views.login_request, name="login"),
    path("logout/", views.logout_request, name="login"),
    path("register/", views.register, name="register"),
    path("findUserByEmail/", views.get_user_by_email, name="find_user_by_email"),
    path("findUserById/<int:id_user>", views.get_user_by_id, name="find_user_by_id"),
    path("updateUser/", views.update_user, name="update_user"),
    path("changePassword/", views.change_password, name="change_password"),
    path("setPassword/", views.set_password, name="set_password"),
    path("tokenPass/", views.token_pass, name="token_pass"),
    path("createEmailValidationToken/", views.create_email_validation_token, name="create_email_validation_token"),
    path("validateEmailToken/", views.validate_email_token, name="validate_email_token"),
    path("confirmPasswordReset/", views.confirm_password_reset, name="confirm_password_reset"),
]
