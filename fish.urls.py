from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # ✅ 중복 로드(Conflicting models) 에러를 막기 위해 모든 경로 앞에 'apps.'를 붙였습니다.
    path('', include('apps.core.urls', namespace='core')),
    path('accounts/', include('apps.accounts.urls', namespace='accounts')),

    # 로그아웃 (기존 로직 유지)
    path('logout/', auth_views.LogoutView.as_view(next_page='/'), name='logout'),

    # ✅ 나머지 서브 앱들도 동일하게 'apps.' 경로로 통일합니다.
    path('monitoring/', include('apps.monitoring.urls', namespace='monitoring')),
    path('reports/', include('apps.reports.urls', namespace='reports')),
    path('chatbot/', include('apps.chatbot.urls', namespace='chatbot')),
]

# 개발 환경에서 media 파일 접근 허용 (기존 로직 유지)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)