from django.urls import path
from . import views

app_name = 'chatbot'

urlpatterns = [
    # 사이드바 챗봇 전용 엔드포인트
    path('ask/', views.ask_chatbot, name='ask'),
]