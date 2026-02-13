from django.shortcuts import render, redirect
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.conf import settings
from .forms import CustomUserCreationForm

# --- 1. 회원가입 기능 ---
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

# --- 2. 로그인 기능 ---
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

# --- 3. 로그아웃 기능 ---
def logout_view(request):
    auth_logout(request)
    messages.success(request, "로그아웃 되었습니다.")
    return redirect('home')

# --- 4. 내 정보 관리 기능 ---
@login_required
def profile_view(request):
    user = request.user
    if request.method == 'POST':
        if hasattr(user, 'nickname'):
            user.nickname = request.POST.get('nickname', user.nickname)
        if hasattr(user, 'birthday'):
            birthday_val = request.POST.get('birthday')
            user.birthday = birthday_val if birthday_val else None
        
        user.email = request.POST.get('email', user.email)
        user.save()
        messages.success(request, "개인정보가 성공적으로 수정되었습니다. ✨")
        return redirect('accounts:profile')
    return render(request, 'accounts/profile.html')