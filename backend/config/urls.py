"""Root URL configuration: admin + the auth and applications APIs under /api/."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/", include("applications.urls")),
]

# NOTE: we do NOT serve MEDIA_URL statically here, in DEBUG or otherwise.
# Resume PDFs are private per user. The only ways to fetch one are the two
# login/secret-gated endpoints (/api/resume/pdf/ for the owner in a browser,
# /api/worker/tasks/<id>/resume.pdf for the trusted worker). A blanket static
# handler would serve them with no auth from a guessable URL.
