from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # 각 앱의 urls.py 연결
    path('', include('core.urls')), 
    path('accounts/', include('accounts.urls', namespace='accounts')),
    
    # [수정] 로그아웃 경로: 명시적으로 다음 페이지(메인)를 지정하여 500 에러 방지
    path('logout/', auth_views.LogoutView.as_view(next_page='/'), name='logout'),
    
    path('monitoring/', include('monitoring.urls', namespace='monitoring')),
    path('reports/', include('reports.urls', namespace='reports')),
    path('chatbot/', include('chatbot.urls', namespace='chatbot')),
]