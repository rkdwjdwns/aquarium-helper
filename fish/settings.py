import os, sys
from pathlib import Path
from dotenv import load_dotenv

# 1. 경로 설정 및 .env 로드
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

# apps 폴더를 파이썬 경로에 등록
sys.path.insert(0, str(BASE_DIR / 'apps'))

# 2. .env에서 값 가져오기
# SECRET_KEY가 .env에 없으면 임시 키를 사용하도록 설정했습니다.
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fish-helper-temp-key-1234')
DEBUG = os.getenv('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = ['*'] # 모든 호스트 허용 (배포 및 핸드폰 접속용)

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
    # 배포(Render) 환경에서 정적 파일을 서빙하기 위해 유용합니다.
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
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

# 정적 파일 설정
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
# 배포 시 수집될 정적 파일 경로
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
AUTH_USER_MODEL = 'accounts.User'

# 4. .env에서 Gemini API Key 가져오기 (수정 완료)
# os.getenv('환경변수이름') 형태로 사용해야 합니다.
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')