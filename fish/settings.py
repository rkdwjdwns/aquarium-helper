import os, sys
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url

# 1. 경로 설정 및 .env 로드
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

# [핵심] apps 폴더 내부의 앱들을 패키지로 인식하도록 경로 등록
APPS_DIR = BASE_DIR / 'apps'
if str(APPS_DIR) not in sys.path:
    sys.path.insert(0, str(APPS_DIR))

# 2. 보안 및 환경 설정
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fish-helper-temp-key-1234')
DEBUG = os.getenv('DEBUG', 'False') == 'True'

# 모든 호스트 허용
ALLOWED_HOSTS = ['*'] 

# CSRF 신뢰할 수 있는 도메인 설정
CSRF_TRUSTED_ORIGINS = [
    'https://*.onrender.com',
    'https://aquarium-helper.onrender.com',
]

# 3. 앱 등록
# 'apps.'을 붙여서 관리하는 구조이므로, Config 클래스명을 명확히 기입합니다.
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    
    # 로컬 앱 (apps 디렉토리 내부)
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
        'DIRS': [
            BASE_DIR / 'templates',
            BASE_DIR / 'apps' / 'monitoring' / 'templates',
        ],
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

# 4. 데이터베이스 설정 (Render PostgreSQL 연동)
RENDER_DB_URL = "postgresql://fishadmin:Zpyvc8UcvJl6crGmBSr6lZrAIPNYpbFA@dpg-d66njmcr85hc739qhod0-a/fishdb_t8jy"

DATABASES = {
    'default': dj_database_url.config(
        default=os.getenv('DATABASE_URL', RENDER_DB_URL if not DEBUG else f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=600,
        ssl_require=not DEBUG
    )
}

AUTH_PASSWORD_VALIDATORS = []

# 5. 국제화 설정
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

# 6. 정적 파일 및 Whitenoise 설정
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage", 
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 7. 유저 모델 및 로그인 설정
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
AUTH_USER_MODEL = 'apps.accounts.User' # [주의] 앱 경로를 명시적으로 표현

# 8. AI 설정
GEMINI_API_KEY_1 = os.getenv('GEMINI_API_KEY_1')
GEMINI_API_KEY_2 = os.getenv('GEMINI_API_KEY_2')
GEMINI_API_KEY_3 = os.getenv('GEMINI_API_KEY_3')
GEMINI_API_KEY = GEMINI_API_KEY_1 or GEMINI_API_KEY_2 or GEMINI_API_KEY_3 or ""

# --- 배포 환경 보안 설정 ---
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000 
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True