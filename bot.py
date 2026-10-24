import os
import datetime
import requests
import google.generativeai as genai

# 설정
TELEGRAM_BOT_TOKEN = "8922920436:AAH_c8eRLeoFsnaJMTOqmaO3pWw0HsaRXuc"
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8273348813")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Gemini 설정
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3.8-flash")

def generate_bureau_cases():
    """
    [비현실문제해결국] 공식 기획안(v0.1)의 세계관, 어조, 톤앤매너를 완벽히 주입한 기획 엔진
    """
    prompt = """
    너는 인스타그램 10만 팔로워 및 고공유·고저장률을 목표로 하는 풍자 콘텐츠 '비현실문제해결국'의 수석 마케터이자 기획자야.
    공식 기획안에 명시된 아래의 핵심 세계관과 원칙을 완벽히 준수하여 기획안을 작성해줘.

    [핵심 세계관 및 기획 원칙]
    1. 기관 존재 이유: "법으로는 안 되고, 참자니 분하고, 말하자니 쪼잔한" 현실의 사소한 억울함을 접수·판정·처분하는 가상의 공공기관 시스템.
    2. 어조 및 톤앤매너: 절대 웃기려 하지 않는 '건조하고 정중한 공문체'. 감정 표현은 철저히 배제(가혹해도 "유감입니다" 수준). 오직 진지한 절차와 서식으로 웃음을 유발할 것[cite: 23].
    3. 1장 훅의 법칙: 처음 보는 유입자는 세계관을 모른다. 장황한 기관 설명 대신, 보는 즉시 "이거 완전 내 얘기인데?" 하며 공유하고 싶어지는 '문제 상황 자체'를 첫 장 훅으로 던질 것[cite: 24].
    4. 타겟 영역: 직장인, 대학생, 인간관계 등에서 일어나는 현대적이고 생생한 일상 부조리 및 트렌드.

    현재 시점에서 화제가 되고 있는 최신 트렌드나 직장인·대학생들의 라이프스타일 이슈를 반영하여, 가상의 공식 기관이 접수·판정할 수 있는 기획 후보 3가지를 도출해 줘.

    각 후보는 반드시 아래 형식과 항목에 맞춰 정갈하게 작성해줘:

    [후보 1]
    - 트렌드/이슈 배경: (현재 시점의 사회적 현상이나 일상 트렌드 한 줄 요약)
    - 사건명: 
    - 접수 유형: (예: 약속 불이행, 소통 단절 등)
    - 처분/판정 가안: (예: 주의, 경미, 재발 시 특정 조치 의무화 등)
    - 첫 장 훅 문구: (설명 없이 즉시 공감과 DM 공유를 부르는 날카로운 한 문장)

    [후보 2]
    (위와 동일한 형식)

    [후보 3]
    (위와 동일한 형식)

    불필요한 마크다운 기호나 이모지는 최소화하고, 실제 정부 공문서 서식 느낌의 정돈된 텍스트로 출력해줘.
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
    print("[비현실문제해결국] 기획안 생성 시스템 가동 중...")
    cases_text = generate_bureau_cases()
    
    full_message = "🏛️ [비현실문제해결국] 금일 접수된 기획 후보 3선\n(공식 기획안 v0.1 세계관 적용)\n\n" + cases_text
    
    # 텔레그램 전송
    if TELEGRAM_CHAT_ID:
        res = send_telegram_message(full_message)
        print("텔레그램 전송 결과:", res)
    else:
        print("TELEGRAM_CHAT_ID가 설정되지 않았습니다.")
        
    # GitHub cases 폴더에 백업 저장
    today = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    os.makedirs("cases", exist_ok=True)
    file_path = f"cases/bureau_plan_{today}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(full_message)
    print(f"기획안 파일 저장 완료: {file_path}")
