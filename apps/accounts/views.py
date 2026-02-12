from django.shortcuts import render, redirect
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib import messages
from .forms import CustomUserCreationForm
from django.contrib.auth.forms import AuthenticationForm
from django.http import JsonResponse
from django.conf import settings

# LangChain 관련 임포트
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

# --- 1. 회원가입/로그인 기능 (기존 기능 복구) ---

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

# --- 2. 챗봇 기능 (Gemini 1.5-flash 적용) ---

def chat_view(request):
    """
    위키독스 가이드를 참고한 LangChain 기반 챗봇 함수 (1.5-flash 고정)
    """
    if request.method == 'POST':
        user_message = request.POST.get('message')
        
        try:
            # 1. Gemini 모델 설정 (1.5-flash 명시)
            llm = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                google_api_key=settings.GEMINI_API_KEY,
                temperature=0.7
            )
            
            # 2. 챗봇의 정체성 설정
            prompt = ChatPromptTemplate.from_messages([
                ("system", "당신은 열대어와 수초 전문가 '어항 도우미'입니다. 답변 마지막에는 [추천 세팅] 정보를 포함해주세요."),
                ("user", "{input}")
            ])
            
            # 3. 체인 실행
            chain = prompt | llm
            response = chain.invoke({"input": user_message})
            
            # 프론트엔드 호환성을 위해 reply와 message 모두 반환
            return JsonResponse({
                'reply': response.content,
                'message': response.content,
                'status': 'success'
            })
            
        except Exception as e:
            print(f"Chat Error: {e}")
            error_msg = str(e)
            if "429" in error_msg:
                friendly_msg = "현재 질문이 너무 많아 구글이 잠시 쉬고 있어요. 1분만 기다려 주세요! 🐠"
            else:
                friendly_msg = "챗봇이 잠시 아픈 것 같아요. 나중에 다시 시도해주세요!"
                
            return JsonResponse({'reply': friendly_msg, 'message': friendly_msg}, status=500)
            
    return render(request, 'accounts/chat.html')