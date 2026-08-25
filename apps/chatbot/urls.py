from django.urls import path
from django.contrib.auth.decorators import login_required
from apps.chatbot.views import (
    chatbot_home,
    ask_chatbot,
    chat_history,
    chat_clear,
    chat_delete_one,
)

app_name = 'chatbot'

urlpatterns = [
    path('',                         login_required(chatbot_home), name='chat_page'),
    path('ask/',                     ask_chatbot,      name='ask'),
    path('history/',                 chat_history,     name='history'),
    path('clear/',                   chat_clear,       name='clear'),
    path('delete/<int:message_id>/', chat_delete_one,  name='delete_one'),
]