from django.shortcuts import render, redirect
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm
from django.http import JsonResponse
from django.conf import settings
from .forms import CustomUserCreationForm  # forms.py가 같은 폴더에 있어야 합니다.

# LangChain 관련 임포트
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

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

# --- 4. LangChain 챗봇 기능 (2.0 모델 적용) ---
def chat_view(request):
    if request.method == 'POST':
        user_message = request.POST.get('message')
        try:
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.0-flash", 
                google_api_key=settings.GEMINI_API_KEY,
                temperature=0.7
            )
            prompt = ChatPromptTemplate.from_messages([
                ("system", "당신은 열대어와 수초 전문가 '어항 도우미'입니다. 답변 마지막에는 [추천 세팅] 정보를 포함해주세요."),
                ("user", "{input}")
            ])
            chain = prompt | llm
            response = chain.invoke({"input": user_message})
            return JsonResponse({
                'reply': response.content,
                'message': response.content,
                'status': 'success'
            })
        except Exception as e:
            print(f"LangChain Error: {e}")
            return JsonResponse({'reply': "서비스 연결에 문제가 발생했습니다.", 'message': str(e)}, status=500)
            
    return render(request, 'accounts/chat.html')