import os
import requests
import google.generativeai as genai

# 설정 (GitHub Secrets 또는 환경 변수에서 불러올 값들)
TELEGRAM_BOT_TOKEN = "8922920436:AAH_c8eRLeoFsnaJMTOqmaO3pWw0HsaRXuc"
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID") 
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")

# Gemini 설정
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3.8-flash")

def generate_unreal_cases():
    """Gemini를 이용해 [비현실문제해결국] 기획 후보 3가지 생성"""
    prompt = """
    너는 인스타그램 10만 팔로워를 목표로 하는 풍자 콘텐츠 '비현실문제해결국'의 전문 마케터이자 기획자야.
    현실의 사소한 억울함, 직장 생활, 인간관계, 대학/학교생활 등에서 공감할 수 있는 소재를 바탕으로,
    가상의 공식 기관이 접수·판정할 수 있는 기획 아이디어 후보 3가지를 만들어줘.
    
    각 후보는 아래 형식으로 작성해줘:
    1. 사건명 (예: 친구의 "밥 한번 먹자" 미이행 건)
    2. 접수 유형 (예: 약속 불이행)
    3. 처분/판정 가안 (예: 재발 시 날짜를 반드시 제시할 것)
    4. 첫 장 훅 문구 (보는 즉시 공감하고 공유하고 싶어지는 한 문장)
    
    건조하고 진지한 공문체 톤앤매너를 유지해줘.
    """
    response = model.generate_content(prompt)
    return response.text

def send_telegram_message(text):
    """텔레그램으로 기획안 전송"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    return response.json()

if __name__ == "__main__":
    print("비현실문제해결국 기획안 생성 중...")
    cases_text = generate_unreal_cases()
    
    header = "🚨 **[비현실문제해결국] 오늘의 기획 후보**\n마음에 드는 후보를 검토해 주세요.\n\n"
    full_message = header + cases_text
    
    if TELEGRAM_CHAT_ID != "YOUR_CHAT_ID":
        res = send_telegram_message(full_message)
        print("텔레그램 전송 결과:", res)
    else:
        print("--- [테스트 출력 (Chat ID 미입력 상태)] ---")
        print(full_message)
