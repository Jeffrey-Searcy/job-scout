"""
Authentication API for the SPA (session-cookie based).

Endpoints (all under /api/auth/):
  - POST   signup/   create an account and log in
  - POST   login/    log in an existing account
  - POST   logout/   log out the current session
  - GET    me/       who am I? (used by the SPA to gate the UI)
  - GET    csrf/     set the CSRF cookie before a login/signup POST

Why sessions, not tokens: the app is a browser SPA behind a private network
with real HTTPS (Tailscale). Django's session cookie + CSRF gives safe,
built-in login with nothing to store client-side. The AI worker does NOT use
this path — it authenticates per task with a scoped token (added in a later
layer), so it never needs a username/password.
"""
from django.contrib.auth import login as django_login, logout as django_logout
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import SignupSerializer, LoginSerializer, UserSerializer


class SignupView(APIView):
    """POST /api/auth/signup/ — create an account, then log it in immediately.

    Open signup is intentional: the app runs on a private Tailscale network, so
    anyone who can reach the URL is already trusted to create an account.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        """Validate, create the user, start a session, return the user."""
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        # Log the new user straight in so they land on their dashboard.
        django_login(request, user)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """POST /api/auth/login/ — authenticate and start a session."""

    permission_classes = [AllowAny]

    def post(self, request):
        """Validate credentials, start the session, return the user."""
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        django_login(request, user)
        return Response(UserSerializer(user).data)


class LogoutView(APIView):
    """POST /api/auth/logout/ — end the current session."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Flush the session; the SPA then returns to the login screen."""
        django_logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(ensure_csrf_cookie, name="get")
class MeView(APIView):
    """GET /api/auth/me/ — the current user, or 401 if not logged in.

    Also carries @ensure_csrf_cookie so a fresh SPA load gets its CSRF cookie
    set on the very first request, before it tries any login/signup POST.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return the logged-in user's public fields."""
        return Response(UserSerializer(request.user).data)


class CsrfView(APIView):
    """GET /api/auth/csrf/ — set the CSRF cookie and return the token.

    The SPA calls this once on load so the browser holds a CSRF cookie before
    it POSTs to login/signup. We call get_token to force the cookie to be sent.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        """Force-set the CSRF cookie and echo the token for header use."""
        return Response({"csrfToken": get_token(request)})
