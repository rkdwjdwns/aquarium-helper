from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # 각 앱의 urls.py를 연결합니다. (sys.path 설정 덕분에 'apps.' 없이 호출 가능)
    path('', include('core.urls')), 
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('monitoring/', include('monitoring.urls', namespace='monitoring')),
    path('reports/', include('reports.urls', namespace='reports')),
    path('chatbot/', include('chatbot.urls', namespace='chatbot')),
]