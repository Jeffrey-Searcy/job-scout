"""App configuration for the applications domain."""
from django.apps import AppConfig


class ApplicationsConfig(AppConfig):
    """Registers the 'applications' app with Django."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "applications"
