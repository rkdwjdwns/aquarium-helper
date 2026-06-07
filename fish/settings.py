import os
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url

# 기본 경로 설정
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

# ✅ sys.path 조작 제거 — apps. 접두사로 통일하므로 불필요

# 보안 및 환경 설정
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fish-helper-temp-key-1234')
DEBUG = os.getenv('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = ['*', 'aquarium-helper.onrender.com']

CSRF_TRUSTED_ORIGINS = [
    'https://*.onrender.com',
    'https://aquarium-helper.onrender.com'
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'whitenoise.runserver_nostatic',

    'apps.accounts.apps.AccountsConfig',
    'apps.core.apps.CoreConfig',
    'apps.monitoring.apps.MonitoringConfig',
    'apps.reports.apps.ReportsConfig',
    'apps.ai.apps.AiConfig',
    'apps.chatbot.apps.ChatbotConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'fish.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'fish.wsgi.application'

DATABASES = {
    'default': dj_database_url.config(
        default=os.getenv('DATABASE_URL', f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=600,
        ssl_require=not DEBUG
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

if not os.path.exists(MEDIA_ROOT):
    os.makedirs(MEDIA_ROOT, exist_ok=True)

AUTH_USER_MODEL = 'accounts.User'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
LOGIN_URL = '/accounts/login/'

SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 1209600
SESSION_SAVE_EVERY_REQUEST = True
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY_1') or os.getenv('GEMINI_API_KEY_2') or ""

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'