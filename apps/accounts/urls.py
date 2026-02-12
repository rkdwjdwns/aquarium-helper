from django.urls import path, reverse_lazy # reverse_lazy 추가
from django.contrib.auth import views as auth_views
from . import views

app_name = 'accounts'

urlpatterns = [
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('chat/', views.chat_view, name='chat'),
    
    # 비밀번호 변경: 성공 시 'password_change_done'으로 가도록 명시
    path('password_change/', 
         auth_views.PasswordChangeView.as_view(
             template_name='accounts/password_change.html',
             success_url=reverse_lazy('accounts:password_change_done') # 이 줄 추가!
         ), 
         name='password_change'),
         
    path('password_change/done/', 
         auth_views.PasswordChangeDoneView.as_view(
             template_name='accounts/password_change_done.html'
         ), 
         name='password_change_done'),
]