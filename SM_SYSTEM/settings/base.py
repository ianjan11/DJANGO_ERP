import os
from pathlib import Path
from celery.schedules import crontab
import dj_database_url

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Core Settings
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "django-insecure-6!g$*$j_!1sscjv7g*r*km5)+o2$(3f!_p_u#)=gd$!lvpl8r%",
)

EXCHANGE_RATE_API_KEY = os.getenv("EXCHANGE_RATE_API_KEY")

# Application definition
INSTALLED_APPS = [
    # Built-in apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Third-party apps
    "bootstrap5",
    "corsheaders",
    "debug_toolbar",
    # Local apps
    "core",
    "users",
    "inventory",
    "accounting",
    "sales",
    "purchases",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "users.middleware.active_company.ActiveCompanyMiddleware",
]

ROOT_URLCONF = "SM_SYSTEM.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "accounting-app" / "dist"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.active_company",
                "core.context_processors.app_navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "SM_SYSTEM.wsgi.application"

AUTH_USER_MODEL = "users.User"

# Database Configuration via dj-database-url
DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# CORS Configuration
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
]

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
USE_I18N = True
USE_TZ = True
TIME_ZONE = "Africa/Dar_es_Salaam"

# Static files
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = []

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Authentication Views & URLs
CSRF_FAILURE_VIEW = "users.views.csrf_failure_view"
LOGIN_URL = "users:login"
LOGIN_REDIRECT_URL = "users:select-company"
LOGOUT_REDIRECT_URL = "users:login"

# Celery Configuration
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
CELERY_TIMEZONE = "UTC"
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

CELERY_BEAT_SCHEDULE = {
    "update-prices-daily": {
        "task": "sales.tasks.update_prices_task",
        "schedule": crontab(minute=0, hour=0),
    }
}

# Logging Configuration
LOG_DIR = BASE_DIR / "logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{levelname}] {asctime} {name} {funcName}: {message}",
            "style": "{",
        },
        "simple": {
            "format": "[{levelname}] {asctime} - {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "core_events_file": {
            "class": "logging.FileHandler",
            "filename": LOG_DIR / "core_events.log",
            "formatter": "verbose",
        },
        "core_handlers_file": {
            "class": "logging.FileHandler",
            "filename": LOG_DIR / "core_handlers.log",
            "formatter": "verbose",
        },
        "sales_invoice_file": {
            "class": "logging.FileHandler",
            "filename": LOG_DIR / "sales_invoice.log",
            "formatter": "verbose",
        },
        "accounting_recon_file": {
            "class": "logging.FileHandler",
            "filename": LOG_DIR / "accounting_reconciliation.log",
            "formatter": "verbose",
        },
        "purchase_invoice_file": {
            "class": "logging.FileHandler",
            "filename": LOG_DIR / "purchases.log",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "core.events.system": {
            "handlers": ["console", "core_events_file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "core.events.handlers": {
            "handlers": ["core_handlers_file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "sales.invoice": {
            "handlers": ["sales_invoice_file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "accounting.reconciliation": {
            "handlers": ["accounting_recon_file", "console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "purchases.invoice": {
            "handlers": ["purchase_invoice_file"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}