"""App config for the accounts app (signup / login / logout / current-user)."""
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Registers the accounts app; holds no models of its own.

    Auth uses Django's built-in ``auth.User``. This app only adds the API
    endpoints (signup, login, logout, me) and the session-auth wiring the SPA
    needs. Per-user *data* ownership lives on the ``applications`` models.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
