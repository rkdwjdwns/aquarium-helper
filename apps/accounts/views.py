from django.shortcuts import render, redirect
from django.contrib.auth import login as auth_login, logout as auth_logout, authenticate
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.conf import settings
from .forms import CustomUserCreationForm

# --- 1. 회원가입 기능 ---
def signup_view(request):
    """회원가입 처리: 가입 완료 후 로그인 페이지로 유도"""
    if request.user.is_authenticated:
        return redirect('/')  # 로그인 상태면 메인으로
        
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            name = getattr(user, 'nickname', None) or user.username
            messages.success(request, f"{name}님, 가입을 축하합니다! 로그인을 해주세요.")
            return redirect('accounts:login')
    else:
        form = CustomUserCreationForm()
    return render(request, 'accounts/signup.html', {'form': form})

# --- 2. 로그인 기능 (로그인 정보 저장 반영) ---
def login_view(request):
    """로그인 처리: '로그인 정보 저장' 체크박스 여부에 따라 세션 만료 시간 설정"""
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
        
    if request.method == 'POST':
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)
            
            # [핵심] 로그인 정보 저장 체크박스 확인
            # HTML input 태그의 name="remember_me" 값을 읽어옵니다.
            remember_me = request.POST.get('remember_me')
            
            if remember_me:
                # 체크 시: settings.SESSION_COOKIE_AGE 설정값(보통 2주) 동안 유지
                request.session.set_expiry(None) 
                messages.info(request, "로그인 정보가 저장되었습니다.")
            else:
                # 체크 안 할 시: 0 설정 (브라우저를 닫으면 로그아웃)
                request.session.set_expiry(0)
            
            name = getattr(user, 'nickname', None) or user.username
            messages.info(request, f"{name}님, 환영합니다! 🌊")
            
            # next 파라미터가 있으면 해당 경로로, 없으면 설정된 메인으로 이동
            next_url = request.GET.get('next') or settings.LOGIN_REDIRECT_URL
            return redirect(next_url)
        else:
            messages.error(request, "아이디 또는 비밀번호가 틀렸습니다.")
    else:
        form = AuthenticationForm()
    return render(request, 'accounts/login.html', {'form': form})

# --- 3. 로그아웃 기능 ---
def logout_view(request):
    """로그아웃 처리 후 메인 페이지로 이동"""
    auth_logout(request)
    messages.success(request, "로그아웃 되었습니다. 다음에 또 오세요! 👋")
    return redirect('/')

# --- 4. 내 정보 관리 기능 ---
@login_required
def profile_view(request):
    """유저 프로필 수정: 닉네임, 이메일 등 업데이트"""
    user = request.user
    if request.method == 'POST':
        # 데이터 업데이트
        user.nickname = request.POST.get('nickname', user.nickname)
        user.email = request.POST.get('email', user.email)
        
        # birthday 필드 존재 여부 확인 후 처리
        if hasattr(user, 'birthday'):
            birthday_val = request.POST.get('birthday')
            user.birthday = birthday_val if birthday_val else None
            
        user.save()
        messages.success(request, "개인정보가 성공적으로 수정되었습니다. ✨")
        return redirect('accounts:profile')
        
    return render(request, 'accounts/profile.html')