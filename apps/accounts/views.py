from django.shortcuts import render, redirect
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib import messages
from .forms import CustomUserCreationForm
from django.contrib.auth.forms import AuthenticationForm

def signup_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"{user.nickname}님, 가입을 축하합니다! 로그인을 해주세요.")
            return redirect('accounts:login')
    else:
        form = CustomUserCreationForm()
    return render(request, 'accounts/signup.html', {'form': form})

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)
            messages.info(request, f"{user.nickname}님, 환영합니다!")
            return redirect('home')
        else:
            messages.error(request, "아이디 또는 비밀번호가 틀렸습니다.")
    else:
        form = AuthenticationForm()
    return render(request, 'accounts/login.html', {'form': form})

def logout_view(request):
    auth_logout(request)
    messages.success(request, "로그아웃 되었습니다.")
    return redirect('home')