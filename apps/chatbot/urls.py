from django.urls import path
from core.views import chat_api, chat_history, chat_clear

app_name = 'chatbot'

urlpatterns = [
    path('ask/',     chat_api,     name='ask'),
    path('history/', chat_history, name='history'),
    path('clear/',   chat_clear,   name='clear'),
]