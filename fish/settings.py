import os
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url

# 기본 경로 설정
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

# ──────────────────────────────────────────────
# 보안 및 환경 설정
# ──────────────────────────────────────────────

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fish-helper-temp-key-1234')
DEBUG = os.getenv('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = ['*', 'aquarium-helper.onrender.com']

CSRF_TRUSTED_ORIGINS = [
    'https://*.onrender.com',
    'https://aquarium-helper.onrender.com',
]

# ──────────────────────────────────────────────
# 앱 설정
# ──────────────────────────────────────────────

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

# ──────────────────────────────────────────────
# 미들웨어
# ──────────────────────────────────────────────

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

# ──────────────────────────────────────────────
# 데이터베이스
# ──────────────────────────────────────────────

DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            ssl_require=not DEBUG,
        )
    }
else:
    # 로컬 개발 환경 (SQLite)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ──────────────────────────────────────────────
# 비밀번호 검증
# ──────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ──────────────────────────────────────────────
# 국제화
# ──────────────────────────────────────────────

LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

# ──────────────────────────────────────────────
# 정적 파일 (Whitenoise)
# static/ 폴더가 없으면 자동 생성
# ──────────────────────────────────────────────

STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

_static_dir = BASE_DIR / 'static'
_static_dir.mkdir(parents=True, exist_ok=True)
STATICFILES_DIRS = [_static_dir]

if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ──────────────────────────────────────────────
# 미디어 파일 (로컬 개발 전용)
# Render 프로덕션에서는 /media/ 미서빙 → demo.mp4 등은 static/ 에 보관
# fish/urls.py 에서 DEBUG 시에만 urlpatterns += static(MEDIA_URL, ...) 추가
# ──────────────────────────────────────────────

MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────
# 인증
# ──────────────────────────────────────────────

AUTH_USER_MODEL       = 'accounts.User'
LOGIN_REDIRECT_URL    = '/'
LOGOUT_REDIRECT_URL   = '/'
LOGIN_URL             = '/accounts/login/'

# ──────────────────────────────────────────────
# 세션 (2주 유지)
# ──────────────────────────────────────────────

SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE              = 1209600   # 2주 (초)
SESSION_SAVE_EVERY_REQUEST      = True
SESSION_ENGINE                  = 'django.contrib.sessions.backends.db'

# ──────────────────────────────────────────────
# Gemini API
# ──────────────────────────────────────────────

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY_1') or os.getenv('GEMINI_API_KEY_2') or ""

# ──────────────────────────────────────────────
# 프로덕션 보안 (Render)
# ──────────────────────────────────────────────

if not DEBUG:
    SECURE_PROXY_SSL_HEADER     = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT         = True
    SESSION_COOKIE_SECURE       = True
    CSRF_COOKIE_SECURE          = True
    SESSION_COOKIE_HTTPONLY     = True
    CSRF_COOKIE_HTTPONLY        = True
    SECURE_HSTS_SECONDS         = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD         = True

# ──────────────────────────────────────────────
# 기타
# ──────────────────────────────────────────────

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'