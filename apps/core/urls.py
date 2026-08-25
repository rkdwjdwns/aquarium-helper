from django.urls import path
from django.views.generic import TemplateView
from . import views

app_name = 'core'

urlpatterns = [
    # 홈 화면
    path('', views.index, name='home'),

    # 오프라인 페이지 (PWA 대응용)
    path('offline/', TemplateView.as_view(template_name='offline.html'), name='offline'),
]