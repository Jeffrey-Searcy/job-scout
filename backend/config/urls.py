"""Root URL configuration: admin + the applications API mounted under /api/."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("applications.urls")),
]
