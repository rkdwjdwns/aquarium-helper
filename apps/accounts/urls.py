from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views
from apps.monitoring import api_views

app_name = 'accounts'

urlpatterns = [
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('api/event-log/', api_views.create_event_log, name='api_event_log'),
    
    # [삭제] path('chat/', views.chat_view, name='chat'), 
    # 위 줄을 삭제함으로써 챗봇 요청이 꼬이는 것을 원천 봉쇄합니다.

    # 비밀번호 변경
    path('password_change/', 
         auth_views.PasswordChangeView.as_view(
             template_name='accounts/password_change.html',
             success_url=reverse_lazy('accounts:password_change_done')
         ), 
         name='password_change'),
         
    path('password_change/done/', 
         auth_views.PasswordChangeDoneView.as_view(
             template_name='accounts/password_change_done.html'
         ), 
         name='password_change_done'),

    path('api/event-log/', api_views.create_event_log, name='api_event_log'),
]