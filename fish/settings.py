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

# ALLOWED_HOSTS 설정 (Render 도메인 명시 권장)
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
    'whitenoise.runserver_nostatic', # 개발 환경에서도 whitenoise 테스트 가능하게 추가
    
    # 로컬 앱 (apps 디렉토리 내)
    'accounts.apps.AccountsConfig',
    'core.apps.CoreConfig',
    'monitoring.apps.MonitoringConfig',
    'reports.apps.ReportsConfig',
    'ai.apps.AiConfig',
    'chatbot.apps.ChatbotConfig',
]

# 미들웨어 (WhiteNoise는 Security 바로 아래 위치가 최적)
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

# 데이터베이스 (PostgreSQL & SQLite 호환)
DATABASES = {
    'default': dj_database_url.config(
        default=os.getenv('DATABASE_URL', f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=600,
        ssl_require=not DEBUG
    )
}

# 비밀번호 검증
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# 언어 및 시간
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

# --- [정적 파일 및 미디어 파일 설정] ---

# 1. 정적 파일 (CSS, JS)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# 배포 환경에서 정적 파일 효율화 (WhiteNoise 최신 설정)
if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# 2. 미디어 파일 (유저 업로드 이미지 등)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# 실제 경로가 없을 경우 생성 (오류 방지)
if not os.path.exists(MEDIA_ROOT):
    os.makedirs(MEDIA_ROOT, exist_ok=True)

# --- [인증 및 유저 모델] ---

AUTH_USER_MODEL = 'accounts.User'
LOGIN_REDIRECT_URL = '/' 
LOGOUT_REDIRECT_URL = '/'
LOGIN_URL = '/accounts/login/'

# 세션 관리
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 1209600
SESSION_SAVE_EVERY_REQUEST = True
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# AI API 설정
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY_1') or os.getenv('GEMINI_API_KEY_2') or ""

# --- [배포 환경 보안 설정] ---

if not DEBUG:
    # Render와 같은 Proxy 뒤에 있을 때 HTTPS 인식 설정
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    
    # 쿠키 보안
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = True
    
    # HSTS 설정 (브라우저가 HTTPS로만 접속하도록 강제)
    SECURE_HSTS_SECONDS = 31536000 # 1년
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# 기본 자동 필드 설정
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'