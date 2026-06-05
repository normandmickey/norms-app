import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if host.strip()]
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "web",
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

ROOT_URLCONF = "norms_app.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "web.context_processors.app_labels",
            ],
        },
    },
]

WSGI_APPLICATION = "norms_app.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "norms_app"),
        "USER": os.environ.get("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = Path(os.environ.get("DJANGO_STATIC_ROOT", BASE_DIR / "staticfiles"))
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT", BASE_DIR.parent / "runtime" / "preview" / "uploads"))
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LIST_MANAGER_API_KEY = os.environ.get("LIST_MANAGER_API_KEY", "")
AGENTMAIL_API_KEY = os.environ.get("AGENTMAIL_API_KEY", "")
AGENTMAIL_API_BASE = os.environ.get("AGENTMAIL_API_BASE", "https://api.agentmail.to/v0")
AGENTMAIL_INBOX_ID = os.environ.get("AGENTMAIL_INBOX_ID", "")
AGENTMAIL_DEFAULT_FROM_NAME = os.environ.get("AGENTMAIL_DEFAULT_FROM_NAME", "norms-app")

JAZZMIN_SETTINGS = {
    "site_title": "norms-app admin",
    "site_header": "norms-app",
    "site_brand": "norms-app",
    "welcome_sign": "Welcome to norms-app",
    "copyright": "SaaSClaw",
    "show_sidebar": True,
    "navigation_expanded": True,
}

CHAT_WIDGET_ENABLED = os.environ.get("CHAT_WIDGET_ENABLED", "false").lower() == "true"
CHAT_WIDGET_PROVIDER = os.environ.get("CHAT_WIDGET_PROVIDER", "openai")
CHAT_WIDGET_API_KEY = os.environ.get("CHAT_WIDGET_API_KEY", "")
CHAT_WIDGET_MODEL = os.environ.get("CHAT_WIDGET_MODEL", "")
CHAT_WIDGET_TITLE = os.environ.get("CHAT_WIDGET_TITLE", "Chat with norms-app")
CHAT_WIDGET_WELCOME_MESSAGE = os.environ.get("CHAT_WIDGET_WELCOME_MESSAGE", "Hi — ask me anything about norms-app.")
CHAT_WIDGET_SYSTEM_PROMPT = os.environ.get("CHAT_WIDGET_SYSTEM_PROMPT", "You are the norms-app assistant. Be concise and helpful.")
CHAT_WIDGET_BUTTON_LABEL = os.environ.get("CHAT_WIDGET_BUTTON_LABEL", "Chat")
APP_AI_PROVIDER = os.environ.get("APP_AI_PROVIDER", CHAT_WIDGET_PROVIDER)
APP_AI_API_KEY = os.environ.get("APP_AI_API_KEY", CHAT_WIDGET_API_KEY)
APP_AI_MODEL = os.environ.get("APP_AI_MODEL", CHAT_WIDGET_MODEL)
APP_AI_SYSTEM_PROMPT = os.environ.get("APP_AI_SYSTEM_PROMPT", "")
