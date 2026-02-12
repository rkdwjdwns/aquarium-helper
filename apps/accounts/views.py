# accounts/views.py 하단 챗봇 부분 수정

def chat_view(request):
    """
    위키독스 가이드를 참고한 LangChain 기반 챗봇 함수 (1.5-flash 고정)
    """
    if request.method == 'POST':
        user_message = request.POST.get('message')
        
        try:
            # 1. Gemini 모델 설정 (1.5-flash 모델로 명시)
            llm = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash", # <--- 여기가 1.5인지 다시 확인!
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
            
            # ⚠️ 프론트엔드 자바스크립트가 'reply'를 받는지 'message'를 받는지 확인이 필요해요.
            # 일단 'reply'와 'message' 둘 다 보내주는 게 안전합니다.
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