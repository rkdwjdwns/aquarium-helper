from django.shortcuts import render, redirect
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.conf import settings
from .forms import CustomUserCreationForm

# --- 1. 회원가입 기능 ---
def signup_view(request):
    if request.user.is_authenticated:
        return redirect('/')  # 안전하게 루트로 리다이렉트
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"{user.nickname or user.username}님, 가입을 축하합니다! 로그인을 해주세요.")
            return redirect('accounts:login')
    else:
        form = CustomUserCreationForm()
    return render(request, 'accounts/signup.html', {'form': form})

# --- 2. 로그인 기능 ---
def login_view(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
        
    if request.method == 'POST':
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)
            # 닉네임이 없으면 유저네임으로 인사
            name = getattr(user, 'nickname', None) or user.username
            messages.info(request, f"{name}님, 환영합니다!")
            
            # next 파라미터가 있으면 해당 경로로, 없으면 설정된 대시보드로 이동
            next_url = request.GET.get('next') or settings.LOGIN_REDIRECT_URL
            return redirect(next_url)
        else:
            messages.error(request, "아이디 또는 비밀번호가 틀렸습니다.")
    else:
        form = AuthenticationForm()
    return render(request, 'accounts/login.html', {'form': form})

# --- 3. 로그아웃 기능 ---
def logout_view(request):
    auth_logout(request)
    messages.success(request, "로그아웃 되었습니다.")
    return redirect('/')

# --- 4. 내 정보 관리 기능 ---
@login_required
def profile_view(request):
    user = request.user
    if request.method == 'POST':
        user.nickname = request.POST.get('nickname', user.nickname)
        user.email = request.POST.get('email', user.email)
        
        # birthday 필드가 모델에 있을 경우에만 처리 (현재 모델엔 없으므로 주석 처리하거나 추가 필요)
        if hasattr(user, 'birthday'):
            birthday_val = request.POST.get('birthday')
            user.birthday = birthday_val if birthday_val else None
            
        user.save()
        messages.success(request, "개인정보가 성공적으로 수정되었습니다. ✨")
        return redirect('accounts:profile')
    return render(request, 'accounts/profile.html')