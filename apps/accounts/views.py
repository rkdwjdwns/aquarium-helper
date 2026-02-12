from django.shortcuts import render, redirect
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib import messages
from .forms import CustomUserCreationForm
from django.contrib.auth.forms import AuthenticationForm
from django.http import JsonResponse  # 챗봇 응답을 위해 추가
from django.conf import settings      # API 키를 가져오기 위해 추가

# 위키독스 방식(LangChain)을 위한 임포트
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

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

# --- 챗봇 기능 추가 구간 ---

def chat_view(request):
    """
    위키독스 가이드를 참고한 LangChain 기반 챗봇 함수
    """
    if request.method == 'POST':
        user_message = request.POST.get('message')
        
        try:
            # 1. Gemini 모델 설정 (Render에 저장한 API KEY 사용)
            llm = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                google_api_key=settings.GEMINI_API_KEY
            )
            
            # 2. 챗봇의 정체성(프롬프트) 설정
            prompt = ChatPromptTemplate.from_messages([
                ("system", "당신은 열대어와 수초 전문가 '어항 도우미'입니다. 사용자의 질문에 친절하게 답하세요."),
                ("user", "{input}")
            ])
            
            # 3. 체인 생성 및 실행 (LangChain 방식)
            chain = prompt | llm
            response = chain.invoke({"input": user_message})
            
            return JsonResponse({'reply': response.content})
            
        except Exception as e:
            # 에러 발생 시 로그를 남기고 사용자에게 알림
            print(f"Chat Error: {e}")
            return JsonResponse({'reply': "죄송합니다. 챗봇이 잠시 아픈 것 같아요. 나중에 다시 시도해주세요!"}, status=500)
            
    # GET 요청 시 챗봇 페이지 보여주기
    return render(request, 'accounts/chat.html')