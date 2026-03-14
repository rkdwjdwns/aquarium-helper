import os, sys
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url

# 기본 경로 설정
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

# 앱 디렉토리 추가 (apps 폴더 내의 앱들을 인식하게 함)
APPS_DIR = BASE_DIR / 'apps'
if str(APPS_DIR) not in sys.path:
    sys.path.insert(0, str(APPS_DIR))

# 보안 및 환경 설정
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fish-helper-temp-key-1234')
DEBUG = os.getenv('DEBUG', 'False') == 'True'

# ALLOWED_HOSTS 설정
ALLOWED_HOSTS = ['*', 'aquarium-helper.onrender.com']

# CSRF 신뢰 도메인
CSRF_TRUSTED_ORIGINS = [
    'https://*.onrender.com', 
    'https://aquarium-helper.onrender.com'
]

# 설치된 앱 목록
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # 서드파티 앱
    'rest_framework',
    'whitenoise.runserver_nostatic', 
    
    # 로컬 앱 (apps 디렉토리 내)
    'accounts.apps.AccountsConfig',
    'core.apps.CoreConfig',
    'monitoring.apps.MonitoringConfig',
    'reports.apps.ReportsConfig',
    'ai.apps.AiConfig',
    'chatbot.apps.ChatbotConfig',
]

# 미들웨어
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

# 템플릿 설정
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

# --- [데이터베이스 설정 - Render 최적화 로직 적용] ---

db_url = os.getenv('DATABASE_URL')

# 1. Render DNS 인식 오류 방지 (dpg- 호스트 자동 완성)
if db_url and "dpg-" in db_url and ".render.com" not in db_url:
    parts = db_url.split("@")
    if len(parts) > 1:
        auth_part = parts[0]
        host_db_part = parts[1]
        if "/" in host_db_part:
            host, db_name = host_db_part.split("/", 1)
            # 내부 주소를 전체 도메인 주소로 보완
            db_url = f"{auth_part}@{host}.render.com/{db_name}"

DATABASES = {
    'default': dj_database_url.config(
        default=db_url or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True, # 연결 안정성 체크
    )
}

# 2. 배포 환경 SSL 설정 강제 (OperationalError 방지 핵심)
if not DEBUG:
    DATABASES['default']['OPTIONS'] = {'sslmode': 'require'}

# --- [정적 파일 및 미디어 파일 설정] ---

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
os.makedirs(MEDIA_ROOT, exist_ok=True)

# --- [인증 및 기타 설정] ---

AUTH_USER_MODEL = 'accounts.User'
LOGIN_REDIRECT_URL = '/' 
LOGOUT_REDIRECT_URL = '/'
LOGIN_URL = '/accounts/login/'

LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

# AI API 설정
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY_1') or os.getenv('GEMINI_API_KEY_2') or ""

# 배포 보안 설정
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'