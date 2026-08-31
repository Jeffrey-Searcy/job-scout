"""
Django settings for the Job Scout backend.

Configuration is environment-driven (12-factor) so the same image runs locally
and in Docker with only env vars changing. Read once at import via django-environ.
"""
from pathlib import Path
import environ

# Project root (…/backend). Used to build absolute paths below.
BASE_DIR = Path(__file__).resolve().parent.parent

# env() reads OS environment variables with typed casting + defaults.
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["*"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:8080", "http://localhost:5173"]),
    CSRF_TRUSTED_ORIGINS=(list, ["http://localhost:8080", "http://localhost:5173"]),
    # HTTPS/cookie hardening. Off by default so plain-HTTP local dev still works;
    # turned ON in the .env when serving over Tailscale HTTPS (see below). When
    # on, the session + CSRF cookies are only sent over HTTPS, which is required
    # for a login served at a real https:// origin.
    SECURE_COOKIES=(bool, False),
    # True when a TLS-terminating proxy (Tailscale `serve`) sits in front and
    # forwards plain HTTP inward. It makes Django trust the
    # X-Forwarded-Proto: https header so request.is_secure() is correct.
    BEHIND_TLS_PROXY=(bool, False),
)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-insecure-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    # Local
    "accounts",
    "applications",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # must precede CommonMiddleware
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# PostgreSQL, configured from a single DATABASE_URL env var (e.g.
# postgres://user:pass@db:5432/jobscout). Falls back to a local dev URL.
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://jobscout:jobscout@db:5432/jobscout",
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded files (currently: user resume PDFs). Stored on a mounted volume in
# Docker so they survive restarts; the media dir is gitignored so real resumes
# never ship. Override MEDIA_ROOT to point at the persistent volume path.
# Leading slash so generated file URLs are absolute paths (/media/…), which
# nginx serves from the shared volume via its `location /media/` block.
MEDIA_URL = "/media/"
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS: allow the React dev server and the dockerized frontend to call the API.
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")

# Login uses session cookies, so cross-origin calls from the SPA must be allowed
# to send those cookies. Without this the browser drops the session cookie and
# every request looks logged-out. The origins above are the only ones trusted.
CORS_ALLOW_CREDENTIALS = True

# CSRF: Django's CsrfViewMiddleware checks the Origin/Referer of unsafe requests
# (POST/PATCH/DELETE) against this list. The SPA's own origin(s) must be here or
# every login/signup POST is rejected with 403. Defaults to the same localhost
# origins as CORS; override CSRF_TRUSTED_ORIGINS for a Tailscale hostname.
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# --- HTTPS behind the Tailscale proxy ---------------------------------------
# Tailscale `serve https` terminates TLS on the host and forwards plain HTTP to
# the frontend nginx, which proxies to Django. So Django's own connection is
# HTTP, but the ORIGINAL request was HTTPS. These settings make Django aware of
# that and lock the cookies to HTTPS. All are OFF for local http:// dev and
# turned on via the .env when serving over the tailnet.

# Trust the proxy's X-Forwarded-Proto header so request.is_secure() is True for
# requests that arrived over HTTPS. Only enable when a trusted TLS proxy is in
# front (Tailscale) — enabling it with no such proxy would let a client spoof it.
if env("BEHIND_TLS_PROXY"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Only send the session + CSRF cookies over HTTPS. Required once the app is
# served at an https:// origin; leave off for plain-HTTP local dev.
SESSION_COOKIE_SECURE = env("SECURE_COOKIES")
CSRF_COOKIE_SECURE = env("SECURE_COOKIES")

# Shared secret the host worker sends to READ the task queue and post distilled
# resume profiles back. It is NOT a per-task credential (those are TaskTokens);
# it only lets the trusted worker see the cross-user pending queue. Empty means
# "worker access not configured": the worker endpoints then reject every request
# with a clear 503 rather than defaulting to an insecure open queue. Set a long
# random value in both the server env and the worker env.
WORKER_SHARED_SECRET = env("WORKER_SHARED_SECRET", default="")

# DRF: JSON in/out. Auth is now REQUIRED by default — every endpoint needs a
# logged-in session unless it opts out with permission_classes = [AllowAny]
# (the auth endpoints do). SessionAuthentication ties requests to the login
# cookie and enforces CSRF on unsafe methods.
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": None,
}
