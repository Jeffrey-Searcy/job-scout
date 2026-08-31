"""
Serializers for the accounts API.

These translate signup/login JSON into validated data and shape the
"current user" response the SPA reads to know who is logged in.
"""
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError
from rest_framework import serializers

User = get_user_model()


class SignupSerializer(serializers.Serializer):
    """Validates a new-account request and creates the user.

    Fields:
      - username: unique login name (case-sensitive, as Django stores it).
      - password: run through Django's configured password validators, so a
        weak password is rejected loudly rather than silently accepted.

    We do not accept ``is_staff``/``is_superuser`` from the client — those are
    never settable via signup, to avoid privilege escalation on an open form.
    """

    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_username(self, value):
        """Reject a username that is blank or already taken."""
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Username cannot be blank.")
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate_password(self, value):
        """Enforce Django's password-strength validators on the raw password."""
        validate_password(value)
        return value

    def create(self, validated_data):
        """Create the user with a properly hashed password.

        validate_username already rejects a name that is taken, but two signups
        with the same name can BOTH pass that check and then race to the DB. The
        unique constraint still protects the data, but the loser would crash with
        a 500. We catch that one race and turn it into the same clean 400 the
        up-front check gives, so the form shows "already taken" instead of an
        error page. We do NOT broaden the except — any other IntegrityError is a
        real bug and must surface.
        """
        # create_user hashes the password; never store it in plain text.
        try:
            return User.objects.create_user(
                username=validated_data["username"],
                password=validated_data["password"],
            )
        except IntegrityError:
            raise serializers.ValidationError(
                {"username": "That username is already taken."}
            )


class LoginSerializer(serializers.Serializer):
    """Validates credentials and resolves them to an authenticated user.

    ``authenticate`` returns None for both a wrong password and an unknown
    user; we surface the same generic error for either, so the form does not
    leak which usernames exist.
    """

    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate(self, attrs):
        """Authenticate the credentials, attaching the user for the view to log in."""
        user = authenticate(
            username=attrs.get("username"),
            password=attrs.get("password"),
        )
        if user is None:
            raise serializers.ValidationError("Incorrect username or password.")
        if not user.is_active:
            raise serializers.ValidationError("This account is disabled.")
        attrs["user"] = user
        return attrs


class UserSerializer(serializers.ModelSerializer):
    """The public shape of a user the SPA reads (never includes the password)."""

    class Meta:
        model = User
        fields = ["id", "username", "is_staff"]
        read_only_fields = fields
