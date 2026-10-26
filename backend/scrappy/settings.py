"""Scrappy backend settings. Everything that changes between machines comes from environment variables
(see .env.example). Nothing secret is written in this file."""
import os
from pathlib import Path
from urllib.parse import urlparse, unquote

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return str(env(name, "1" if default else "0")).lower() in ("1", "true", "yes", "on")


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-change-me-0123456789abcdef0123456789abcdef"
    else:
        raise RuntimeError("Set DJANGO_SECRET_KEY (a long random string) before running in production.")

ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.postgres",
    "django.contrib.staticfiles",
    "core",
    "kwd",
    "portal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",          # serves /static/ (the staff app's scripts, styles and pictures)
    "core.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "portal.gate.PortalGate",                              # one login; the role decides which dashboard opens
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
X_FRAME_OPTIONS = "DENY"
# Every data call carries a login token in a header, so the data calls cannot be forged from another site and the CSRF
# middleware is deliberately not installed. The one cookie (portal.gate) only decides which PAGE opens; it never authorises a
# data call, and it is SameSite=Lax + http-only.
SILENCED_SYSTEM_CHECKS = ["security.W003"]

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": []},
}]

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_USE_FINDERS = True        # serve the apps' static folders directly; `collectstatic` is optional
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_MAX_AGE = 0 if DEBUG else 60 * 60 * 24  # don't keep stale JS while developing

ROOT_URLCONF = "scrappy.urls"
WSGI_APPLICATION = "scrappy.wsgi.application"
AUTH_USER_MODEL = "core.User"
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# imported Supabase logins keep working: Supabase stores bcrypt hashes, Django can verify them
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.BCryptPasswordHasher",
]


def _database():
    url = env("DATABASE_URL", "")
    if url:
        u = urlparse(url)
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": u.path.lstrip("/"),
            "USER": unquote(u.username or ""),
            "PASSWORD": unquote(u.password or ""),
            "HOST": u.hostname or "localhost",
            "PORT": str(u.port or 5432),
            "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "60")),
        }
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "scrappy"),
        "USER": env("DB_USER", "postgres"),
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
        "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "60")),
    }


DATABASES = {"default": _database()}

LANGUAGE_CODE = "en-in"
TIME_ZONE = "UTC"  # the database keeps UTC; every "day" in a report is worked out in Asia/Kolkata
USE_TZ = True
USE_I18N = False

# ---- Scrappy settings ----
JWT_SECRET = env("JWT_SECRET", SECRET_KEY)
ACCESS_TOKEN_SECONDS = int(env("ACCESS_TOKEN_SECONDS", "3600"))
REFRESH_TOKEN_DAYS = int(env("REFRESH_TOKEN_DAYS", "30"))
REFRESH_REUSE_SECONDS = 60       # a refresh token that was just replaced still works for a minute (two tabs refreshing at once)
LOGIN_MAX_FAILURES = int(env("LOGIN_MAX_FAILURES", "10"))
LOGIN_LOCK_SECONDS = int(env("LOGIN_LOCK_SECONDS", "900"))
SINGLE_SESSION = env_bool("SINGLE_SESSION", True)   # newest login wins, like before

PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")  # used in the customer's bill link
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))
FRONTEND_DIR = env("FRONTEND_DIR", "")   # optional: folder with the scrappy_app files, served by this server at /
CORS_ALLOWED_ORIGINS = [o.strip() for o in env("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip() and o.strip() != "*"]
BILL_BADGE_FILE = Path(env("BILL_BADGE_FILE", str(BASE_DIR / "core" / "static_assets" / "bill-badge.png")))

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
if env("REDIS_URL"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": env("REDIS_URL")}}
elif not DEBUG:
    raise RuntimeError("Set REDIS_URL in production; login rate limits require a shared cache.")

if not DEBUG:
    # live sites are https only. Set SECURE_SSL_REDIRECT=0 only for a quick test over plain http.
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "31536000" if SECURE_SSL_REDIRECT else "0"))
    SECURE_CONTENT_TYPE_NOSNIFF = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
