"""URL routing for the accounts (auth) API, mounted under /api/auth/."""
from django.urls import path

from .views import SignupView, LoginView, LogoutView, MeView, CsrfView

urlpatterns = [
    path("signup/", SignupView.as_view(), name="signup"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    path("csrf/", CsrfView.as_view(), name="csrf"),
]
