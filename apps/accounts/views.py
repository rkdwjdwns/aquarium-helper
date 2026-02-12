# --- LangChain 챗봇 기능 수정 버전 ---
def chat_view(request):
    if request.method == 'POST':
        user_message = request.POST.get('message')
        try:
            llm = ChatGoogleGenerativeAI(
                # LangChain에서도 models/ 를 떼고 2.0 버전으로 시도하는 것이 가장 안전합니다.
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
            # 에러 로그를 터미널에 찍어서 확인 가능하게 함
            print(f"LangChain Error: {e}")
            return JsonResponse({'reply': "서비스 연결에 문제가 발생했습니다.", 'message': str(e)}, status=500)
            
    return render(request, 'accounts/chat.html')