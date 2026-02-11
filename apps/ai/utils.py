import google.generativeai as genai
from django.conf import settings

def generate_aquarium_report(tank_name, sensor_data):
    # API 키 설정 (settings.py에 GEMINI_API_KEY를 추가해야 합니다)
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

    # AI에게 보낼 프롬프트 구성
    prompt = f"""
    당신은 스마트 어항 관리 전문가입니다. 
    어항 이름: {tank_name}
    최근 데이터: {sensor_data}
    
    위 데이터를 바탕으로 수질 상태를 분석하고, 
    1. 현재 상태 요약
    2. 주의해야 할 점
    3. 관리 팁
    세 가지 항목으로 나누어 친절하게 리포트를 작성해 주세요. 한국어로 작성해 주세요.
    """
    
    response = model.generate_content(prompt)
    return response.text