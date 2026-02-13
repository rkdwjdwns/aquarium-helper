import os, sys
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url

# 1. 경로 설정 및 .env 로드
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

# apps 폴더 등록 (monitoring, accounts 등이 이 안에 있다면 필수)
APPS_DIR = BASE_DIR / 'apps'
sys.path.insert(0, str(APPS_DIR))

# 2. 보안 및 환경 설정
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fish-helper-temp-key-1234')
DEBUG = os.getenv('DEBUG', 'False') == 'True'

# 모든 호스트 허용 (배포 초기에는 *가 편합니다)
ALLOWED_HOSTS = ['*'] 

# CSRF 신뢰할 수 있는 도메인 설정 (Render 주소를 명확히 추가)
CSRF_TRUSTED_ORIGINS = [
    'https://*.onrender.com',
]

# 3. 앱 등록
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'accounts',
    'core',
    'monitoring',
    'reports',
    'ai',
    'chatbot',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', # 반드시 SecurityMiddleware 바로 아래 위치
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

# 4. 데이터베이스 설정 (Render PostgreSQL 연동)
DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600
    )
}

# 개발 편의를 위해 비밀번호 유효성 검사 완화 (필요시 복구)
AUTH_PASSWORD_VALIDATORS = []

# 5. 국제화 설정
LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

# 6. 정적 파일 및 Whitenoise 설정
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
STATIC_ROOT = BASE_DIR / 'staticfiles'

# [수정] 배포 시 정적 파일 누락으로 인한 500 에러 방지를 위해 유연한 백엔드로 변경
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage", # Manifest 제외 (에러 방지)
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 7. 유저 모델 및 로그인 설정
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
AUTH_USER_MODEL = 'accounts.User'

# --- [중요] 배포 환경 보안 설정 ---
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_COOKIE_SAMESITE = 'Lax'
    
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True # HTTPS 리다이렉트 활성화
    
    # HSTS 설정 (배포가 완전히 확인된 후 켜는 것이 좋지만 유지함)
    SECURE_HSTS_SECONDS = 31536000 
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# 8. AI 설정 (Gemini API KEY)
GEMINI_API_KEY_1 = os.getenv('GEMINI_API_KEY_1')
GEMINI_API_KEY_2 = os.getenv('GEMINI_API_KEY_2')
GEMINI_API_KEY_3 = os.getenv('GEMINI_API_KEY_3')
GEMINI_API_KEY = GEMINI_API_KEY_1 or GEMINI_API_KEY_2 or GEMINI_API_KEY_3 or ""