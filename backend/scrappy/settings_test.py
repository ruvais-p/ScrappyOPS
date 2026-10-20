"""Settings for running the tests quickly: passwords are hashed with a cheap method (never use this on a live system)."""
from .settings import *  # noqa

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.BCryptPasswordHasher",
]
