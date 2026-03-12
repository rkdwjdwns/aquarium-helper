# apps/core/urls.py
from django.urls import path
from . import views  # 같은 폴더이므로 상대 경로 임포트는 괜찮습니다.

app_name = 'core' # 네임스페이스 추가

urlpatterns = [
    path('', views.index, name='home'),
    path('chatbot/ask/', views.chat_api, name='chat_api'),
]