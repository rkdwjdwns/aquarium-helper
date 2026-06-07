from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # 각 앱의 urls.py 연결
    path('', include('core.urls')),
    path('accounts/', include('accounts.urls', namespace='accounts')),

    # 로그아웃
    path('logout/', auth_views.LogoutView.as_view(next_page='/'), name='logout'),

    path('monitoring/', include('monitoring.urls', namespace='monitoring')),
    path('reports/', include('reports.urls', namespace='reports')),
    path('chatbot/', include('chatbot.urls', namespace='chatbot')),
]

# 개발 환경에서 media 파일 접근 허용
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)