from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
import sys
import os

# 1. 뷰 임포트
# settings.py에서 sys.path.insert(0, str(BASE_DIR / 'apps'))를 설정했으므로,
# 실제 실행 시에는 아래 경로로 충분히 작동합니다.
try:
    from core.views import home
except ImportError:
    # 에디터가 경로를 못 찾을 경우를 대비한 대체 경로입니다.
    # 여전히 노란 줄이 뜬다면 에디터 설정(extraPaths)을 확인해 보세요!
    from apps.core.views import home 

urlpatterns = [
    # 관리자 페이지
    path('admin/', admin.site.urls),
    
    # 메인 페이지
    path('', home, name='home'),

    # 2. 인증 관련 URL
    # accounts.urls 내부에 logout이 있더라도, 403 에러 방지를 위해
    # 최상위에서 명시적으로 로그아웃 뷰를 한 번 더 정의해 주는 것이 안전합니다.
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # accounts 앱의 URL 설정을 포함 (login, signup 등)
    path('accounts/', include('accounts.urls')),

    # 3. 서비스 기능별 URL
    path('monitoring/', include('monitoring.urls')),
    path('reports/', include('reports.urls')),
    path('chatbot/', include('chatbot.urls')),
]