# apps/chatbot/urls.py
from django.urls import path
try:
    from core.views import chat_api
except ImportError:
    from apps.core.views import chat_api

app_name = 'chatbot'

urlpatterns = [
    # base.html의 fetch('/chatbot/ask/')와 매칭됩니다.
    path('ask/', chat_api, name='ask'),
]