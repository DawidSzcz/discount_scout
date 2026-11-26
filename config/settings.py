"""Django settings for discount_scout. All deploy-specific values come from env vars (see .env.example)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return env(name, str(default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "procrastinate.contrib.django",
    "scout",
]

MIDDLEWARE = [
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
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "discount_scout"),
        "USER": env("POSTGRES_USER", "discount_scout"),
        "PASSWORD": env("POSTGRES_PASSWORD", "discount_scout"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Email: Gmail SMTP with an app password (https://myaccount.google.com/apppasswords).
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "discount-scout@localhost")

GEMINI_API_KEY = env("GEMINI_API_KEY", "")
# Free keys (2026-11): only the lite model answers reliably; search grounding needs billing.
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Allegro REST API (client_credentials, read-only public offers). Allegro requires this UA.
ALLEGRO_CLIENT_ID = env("ALLEGRO_CLIENT_ID", "")
ALLEGRO_CLIENT_SECRET = env("ALLEGRO_CLIENT_SECRET", "")
ALLEGRO_USER_AGENT = env(
    "ALLEGRO_USER_AGENT", "discount_scout/1.0.0 (+https://github.com/DawidSzcz/discount_scout)"
)

# Where alerts and summaries go if Settings.notify_email is empty.
SCOUT_NOTIFY_EMAIL = env("SCOUT_NOTIFY_EMAIL", "")

# v1 is single-user with no login: every request acts as this user (created on first use).
SCOUT_DEFAULT_USERNAME = env("SCOUT_DEFAULT_USERNAME", "owner")

# Runtime files (browser cookies, debug snapshots). Not committed.
SCOUT_VAR_DIR = env("SCOUT_VAR_DIR", str(BASE_DIR / "var"))
# Random gap between two requests to the same shop, in seconds (PLAN.md section 6).
SCOUT_SHOP_GAP_SECONDS = (float(env("SCOUT_SHOP_GAP_MIN", "5")), float(env("SCOUT_SHOP_GAP_MAX", "20")))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "loggers": {"scout": {"handlers": ["console"], "level": env("SCOUT_LOG_LEVEL", "INFO")}},
}
