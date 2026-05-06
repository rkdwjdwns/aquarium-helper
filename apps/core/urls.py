# apps/core/urls.py
from django.urls import path
from django.views.generic import TemplateView
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.index, name='home'),
    path('chatbot/ask/', views.chat_api, name='chat_api'),
    path('offline/', TemplateView.as_view(template_name='offline.html'), name='offline'),
]