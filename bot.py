import os
import datetime
import urllib.request
import xml.etree.ElementTree as ET
import requests
import google.generativeai as genai

# 설정
TELEGRAM_BOT_TOKEN = "8922920436:AAH_c8eRLeoFsnaJMTOqmaO3pWw0HsaRXuc"
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8273348813")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Gemini 설정
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3.8-flash")

def fetch_recent_news():
    """구글 뉴스 RSS를 통해 직장인/대학생/일상 관련 실시간 최신 뉴스 및 링크 수집"""
    url = "https://news.google.com/rss/search?q=직장인+대학생+MZ+이슈+사회&hl=ko&gl=KR&ceid=KR:ko"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            xml_data = response.read()
        
        root = ET.fromstring(xml_data)
        news_items = []
        for item in root.findall('.//item')[:12]: # 상위 12개 최신 뉴스 추출
            title_elem = item.find('title')
            link_elem = item.find('link')
            pub_date_elem = item.find('pubDate')
            
            title = title_elem.text if title_elem is not None else "제목 없음"
            link = link_elem.text if link_elem is not None else "링크 없음"
            pub_date = pub_date_elem.text if pub_date_elem is not None else ""
            
            news_items.append(f"- 제목: {title}\n  링크: {link}\n  일시: {pub_date}\n")
        return "\n".join(news_items)
    except Exception as e:
        return f"뉴스 수집 중 오류 발생: {e}"

def generate_bureau_cases_with_news(news_text):
    """
    실제 뉴스 데이터를 기반으로 [비현실문제해결국] 세계관을 입혀 기획 후보 3개와 실제 링크를 생성
    """
    prompt = f"""
    너는 인스타그램 10만 팔로워 및 고공유·고저장률을 목표로 하는 풍자 콘텐츠 '비현실문제해결국'의 수석 마케터이자 기획자야.
    공식 기획안 세계관("법으로는 안 되고 참자니 쪼잔한 억울함을 가상 기관이 공문체로 접수·판정")을 완벽히 준수해줘[cite: 23].

    아래 제공된 [실제 최신 뉴스 및 이슈 목록] 중 오늘 또는 최근 1~2일 내의 가장 공감 가고 화제성이 높은 이슈 3가지를 선정하고, 
    각각을 우리 기관의 사건으로 변환하여 기획안을 만들어줘. 
    **반드시 아래 목록에 있는 실제 기사 링크를 각 후보에 정확히 첨부해야 한다.**

    [실제 최신 뉴스 및 이슈 목록]
    {news_text}

    각 후보는 반드시 아래 형식에 맞춰 작성해줘:

    [후보 1]
    - 실제 기사 링크: (위 뉴스 목록의 링크 URL 그대로 기입)
    - 트렌드/이슈 배경: (선정한 실제 뉴스 요약)
    - 사건명: 
    - 접수 유형: 
    - 처분/판정 가안: 
    - 첫 장 훅 문구: (세계관 설명 없이 즉시 공감과 공유를 부르는 날카로운 한 문장)[cite: 24]

    [후보 2]
    (위와 동일한 형식, 다른 기사 선택)

    [후보 3]
    (위와 동일한 형식, 다른 기사 선택)

    건조하고 진지한 공문체 톤앤매너를 유지할 것[cite: 23].
    """
    response = model.generate_content(prompt)
    return response.text

def send_telegram_message(text):
    """텔레그램으로 기획안 전송"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False # 링크 미리보기 허용
    }
    response = requests.post(url, json=payload)
    return response.json()

if __name__ == "__main__":
    print("[비현실문제해결국] 실시간 뉴스 수집 및 기획안 생성 시작...")
    
    # 1. 실시간 뉴스 긁어오기
    news_data = fetch_recent_news()
    
    # 2. Gemini를 통해 뉴스 기반 기획안 생성
    cases_text = generate_bureau_cases_with_news(news_data)
    
    full_message = "🏛️ [비현실문제해결국] 실시간 이슈 연동 기획 후보 3선\n\n" + cases_text
    
    # 3. 텔레그램 전송
    if TELEGRAM_CHAT_ID:
        res = send_telegram_message(full_message)
        print("텔레그램 전송 결과:", res)
        
    # 4. 파일 백업 저장
    today = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    os.makedirs("cases", exist_ok=True)
    file_path = f"cases/news_plan_{today}.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(full_message)
    print(f"기획안 파일 저장 완료: {file_path}")
