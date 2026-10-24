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

# GitHub Actions 입력 변수
ACTION_TYPE = os.environ.get("ACTION_TYPE", "generate_trends")
CHOICE_NUMBER = os.environ.get("CHOICE_NUMBER", "1")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3.8-flash")

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False
    }
    response = requests.post(url, json=payload)
    return response.json()

def fetch_recent_news():
    """실시간 뉴스 RSS 수집 (최근 1~2일 이내 이슈 타겟팅)"""
    url = "https://news.google.com/rss/search?q=직장인+대학생+MZ+이슈+사회&hl=ko&gl=KR&ceid=KR:ko"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        news_items = []
        for item in root.findall('.//item')[:12]:
            title = item.find('title').text if item.find('title') is not None else ""
            link = item.find('link').text if item.find('link') is not None else ""
            pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
            news_items.append(- 제목: {title}\n  링크: {link}\n  일시: {pub_date}\n)
        return "\n".join(news_items)
    except Exception as e:
        return 뉴스 수집 실패: {e}

if __name__ == "__main__":
    print(f"[비현실문제해결국] 정밀 기획 엔진 가동 중 (모드: {ACTION_TYPE})...")

    if ACTION_TYPE == "generate_trends" or ACTION_TYPE == "":
        news_data = fetch_recent_news()
        
        # 초정밀 프롬프트 적용 (기획안 문서 원칙 완전 내재화)
        prompt = f"""
        너는 인스타그램 10만 팔로워 및 고공유·고저장률을 목표로 하는 풍자 콘텐츠 '비현실문제해결국'의 수석 마케터이자 기획자야[cite: 5, 23].
        아래 제공된 [공식 기획안 핵심 철학]과 [실제 최신 뉴스 목록]을 바탕으로, 정확히 3개의 기획 후보를 도출해줘[cite: 5, 23].

        [공식 기획안 핵심 철학]
        1. 존재 이유: "법으로는 안 되고, 참자니 분하고, 말하자니 쪼잔한" 현실의 사소한 억울함만 접수·판정·처분한다.
        2. 톤앤매너: 절대 웃기려 하지 않는 '건조하고 정중한 공문체'. 감정 표현 금지(가혹해도 "유감입니다" 수준). 진지한 절차가 곧 웃음의 원천이다[cite: 23].
        3. 1장 훅 원칙: 처음 보는 유입자는 세계관을 모른다. 기관 설명은 배제하고, 보는 즉시 "이거 완전 내 얘기인데?" 하며 DM 공유를 부르는 날카로운 문제 상황을 첫 장 훅으로 던진다[cite: 7, 15, 24].
        4. 안전 장치: 실존 인물/부처명 금지, 제도를 풍자할 것[cite: 24].

        [실제 최신 뉴스 및 이슈 목록]
        {news_data}

        위 뉴스 중 가장 공감 가고 화제성 높은 3개를 골라 아래 형식에 맞춰 정확히 작성해줘. 
        반드시 실제 뉴스 기사 링크를 각 후보에 정확히 첨부할 것.

        [후보 1]
        - 실제 기사 링크: (위 뉴스 목록의 링크 URL 그대로 기입)
        - 트렌드/이슈 배경: (선정한 실제 뉴스 요약)
        - 사건명: (예: 친구의 "밥 한번 먹자" 미이행 건)
        - 접수 유형: (예: 약속 불이행, 소통 단절 등)
        - 처분/판정 가안: (예: 주의, 경미, 재발 시 특정 조치 의무화 등)
        - 첫 장 훅 문구: (설명 없이 즉시 공감과 공유를 부르는 날카로운 한 문장)[cite: 24]

        [후보 2]
        (위와 동일한 형식, 다른 기사 선택)

        [후보 3]
        (위와 동일한 형식, 다른 기사 선택)
        """
        
        response = model.generate_content(prompt)
        full_message = "🏛️ [비현실문제해결국] 실시간 이슈 기반 기획 후보 3선\n(공식 기획안 v0.1 세계관 적용)\n\n" + response.text
        send_telegram_message(full_message)

    elif ACTION_TYPE == "select_choice":
        prompt = f"""
        너는 '비현실문제해결국' 수석 마케터야. 
        사용자가 제안된 3가지 후보 중 **{CHOICE_NUMBER}번**을 선택했어[cite: 5].
        이 선택된 주제를 바탕으로 인스타그램 캐러셀 피드에 즉시 활용할 수 있는 [상세 판정 보고서]와 [인스타그램 본문 텍스트]를 작성해줘[cite: 3, 12].

        작성 원칙:
        - 건조하고 엄정한 공문체 유지[cite: 23].
        - 해시태그는 절대 포함하지 않음 (공식 정부 정책 안내문 같은 문체).
        - 문서번호, 사건번호, 판정 등 오피셜한 서식을 완벽히 갖출 것[cite: 20, 23].
        """
        response = model.generate_content(prompt)
        full_message = f"✅ [비현실문제해결국] 제 {CHOICE_NUMBER}호 사건 상세 판정안\n\n" + response.text
        send_telegram_message(full_message)

    elif ACTION_TYPE == "reject_regenerate":
        news_data = fetch_recent_news()
        prompt = f"""
        이전에 제시된 후보들이 모두 반려되었습니다. 
        공식 기획안 세계관("건조한 공문체, 사소한 억울함의 제도화")을 준수하여, 완전히 새롭고 참신한 관점으로 직장인/대학생 억울함 이슈 3가지를 다시 기획해주세요[cite: 23]. 실제 기사 링크 필수 포함.
        [실제 최신 뉴스]
        {news_data}
        """
        response = model.generate_content(prompt)
        full_message = "🔄 [비현실문제해결국] 반려로 인한 신규 기획 후보 3선 재발송\n\n" + response.text
        send_telegram_message(full_message)

    print("작업 완료")
