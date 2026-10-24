import os
import datetime
import requests
import google.generativeai as genai

# 설정 (GitHub Secrets에서 환경 변수로 안전하게 불러오기)
TELEGRAM_BOT_TOKEN = "8922920436:AAH_c8eRLeoFsnaJMTOqmaO3pWw0HsaRXuc"
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Gemini 설정
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3.8-flash")

def generate_trend_cases():
    """최근 사회적 이슈나 트렌드를 반영한 [비현실문제해결국] 기획 후보 3가지 생성"""
    prompt = """
    너는 인스타그램 10만 팔로워를 목표로 하는 풍자 콘텐츠 '비현실문제해결국'의 전문 마케터이자 기획자야.
    현재 직장인, 대학생, 인간관계에서 화제가 될 만한 가상의 최신 이슈/트렌드 3가지를 먼저 선정하고,
    각 이슈별로 가상의 공식 기관이 접수·판정할 수 있는 [비현실문제해결국] 기획안을 만들어줘.
    
    각 후보는 아래 형식으로 명확하게 구분해서 작성해줘:
    
    [후보 1]
    - 트렌드/이슈 배경: (어떤 상황인지 한 줄 요약)
    - 사건명: 
    - 접수 유형: 
    - 처분/판정 가안: 
    - 첫 장 훅 문구: 

    [후보 2]
    (위와 동일한 형식)

    [후보 3]
    (위와 동일한 형식)
    
    건조하고 진지한 공문체 톤앤매너를 유지해줘. 특수문자나 복잡한 마크다운 기호는 가급적 쓰지 마.
    """
    response = model.generate_content(prompt)
    return response.text

def send_telegram_message(text):
    """텔레그램으로 기획안 전송"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }
    response = requests.post(url, json=payload)
    return response.json()

if __name__ == "__main__":
    print("최신 트렌드 및 비현실문제해결국 기획안 생성 중...")
    cases_text = generate_trend_cases()
    
    full_message = "🚨 [비현실문제해결국] 최신 트렌드 기획 후보 3선\n\n" + cases_text
    
    # 텔레그램 전송 (Secret에 등록된 ID가 있을 때만 전송)
    if TELEGRAM_CHAT_ID:
        res = send_telegram_message(full_message)
        print("텔레그램 전송 결과:", res)
    else:
        print("TELEGRAM_CHAT_ID가 설정되지 않았습니다.")
        
    # 파일 백업 저장 (깃허브 cases 폴더에도 안전하게 동시 저장)
    today = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    os.makedirs("cases", exist_ok=True)
    file_path = f"cases/trend_plan_{today}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(full_message)
    print(f"기획안 파일 저장 완료: {file_path}")
