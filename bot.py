import os
import datetime
import google.generativeai as genai

# 설정
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")

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
    - 사건명: (예: 친구의 "밥 한번 먹자" 미이행 건)
    - 접수 유형: (예: 약속 불이행)
    - 처분/판정 가안: (예: 재발 시 날짜를 반드시 제시할 것)
    - 첫 장 훅 문구: (보는 즉시 공감하고 공유하고 싶어지는 한 문장)

    [후보 2]
    (위와 동일한 형식)

    [후보 3]
    (위와 동일한 형식)
    
    건조하고 진지한 공문체 톤앤매너를 유지해줘. 특수문자나 복잡한 마크다운 기호는 가급적 쓰지 마.
    """
    response = model.generate_content(prompt)
    return response.text

if __name__ == "__main__":
    print("최신 트렌드 및 비현실문제해결국 기획안 생성 중...")
    cases_text = generate_trend_cases()
    
    # 오늘 날짜 기반 파일 이름 생성
    today = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    os.makedirs("cases", exist_ok=True)
    file_path = f"cases/trend_plan_{today}.txt"
    
    # 결과 내용을 텍스트 파일로 저장
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("[비현실문제해결국] 최신 트렌드 기반 기획 후보 3선\n\n" + cases_text)
        
    print(f"트렌드 기획안 파일 저장 완료: {file_path}")
