from django.urls import path
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from apps.core.views import chat_api, chat_history, chat_clear, chat_delete_one

app_name = 'chatbot'


# ??ì¶”ê?: chat.html ?Œë”ë§?ë·?def chat_page(request):
    return render(request, 'chatbot/chat.html')


urlpatterns = [
    # ?€?€ ì±„íŒ… ?˜ì´ì§€ (?€???´ì—­ ?¬í•¨) ?€?€
    path('',                         login_required(chat_page), name='chat_page'),

    # ?€?€ API ?€?€
    path('ask/',                     chat_api,        name='ask'),
    path('history/',                 chat_history,    name='history'),
    path('clear/',                   chat_clear,      name='clear'),
    path('delete/<int:message_id>/', chat_delete_one, name='delete_one'),
]
