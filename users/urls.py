from django.urls import path
from .views import (
    register,
    login_view,
    profile,
    reset_password,
    home,
    clear_booking_history,
    clear_payment_history,
)
from django.contrib.auth import views as auth_views

class CustomLogoutView(auth_views.LogoutView):
    def get(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs)

urlpatterns = [
    path('',home,name='home'),
    path('register/', register, name='register'),
    path('login/', login_view, name='login'),
    path('profile/', profile, name='profile'),
    path(
    'profile/clear-booking-history/',
    clear_booking_history,
    name='clear_booking_history'
),
path(
    'profile/clear-payment-history/',
    clear_payment_history,
    name='clear_payment_history'
),
    path('reset-password/', reset_password, name='reset-password'),
    path('logout/', auth_views.LogoutView.as_view(template_name='users/logout.html'), name='logout'),
    path('password-reset/',
         auth_views.PasswordResetView.as_view(template_name='users/reset_password.html'),
         name='password_reset'),
    path('password-reset/done/',
         auth_views.PasswordResetDoneView.as_view(template_name='users/password_reset_done.html'),
         name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(template_name='users/password_reset_confirm.html'),
         name='password_reset_confirm'),
    path('password-reset-complete/',
         auth_views.PasswordResetCompleteView.as_view(template_name='users/password_reset_complete.html'),
         name='password_reset_complete'),
]
