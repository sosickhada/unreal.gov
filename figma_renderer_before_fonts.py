from pathlib import Path
import asyncio, html
from playwright.async_api import async_playwright
WIDTH, HEIGHT = 1080, 1350

def make_html(s, i, n, title):
    esc=lambda x: html.escape(str(x or ''))
    headline=esc(s.get('headline')).replace('\n','<br>')
    body=esc(s.get('body')).replace('\n','<br>')
    return '''<!doctype html><html lang="ko"><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;width:1080px;height:1350px;background:#f3f1e9;color:#142b43;font-family:Pretendard,'Noto Sans KR',Arial,sans-serif}.page{height:1350px;padding:72px 78px;display:flex;flex-direction:column;background:linear-gradient(135deg,#faf9f4,#ece9df)}.top{display:flex;justify-content:space-between;border-bottom:2px solid #142b43;padding-bottom:25px;font-size:25px;font-weight:800}.seal{border:2px solid #0b6b58;color:#0b6b58;border-radius:50%;width:44px;height:44px;text-align:center;padding-top:7px}.content{flex:1;display:flex;flex-direction:column;justify-content:center}.eyebrow{font-size:24px;color:#0b6b58;font-weight:700;margin-bottom:32px}h1{font-size:61px;line-height:1.28;letter-spacing:-2px;margin:0 0 30px;word-break:keep-all}.rule{height:8px;background:#0b6b58;margin-bottom:26px}.body{font-size:31px;line-height:1.65;color:#34495a;word-break:keep-all}.case{font-size:22px;color:#5b6a75;margin-top:32px}.bottom{border-top:1px solid #b9c2c5;padding-top:22px;display:flex;justify-content:space-between;font-size:17px;color:#63717b}
</style><body><main class="page"><div class="top"><span>비현실문제부 / NONSENSE AFFAIRS</span><span class="seal">비</span></div><section class="content"><div class="eyebrow">'''+esc(s.get('eyebrow','비현실문제부 · 심의 기록'))+'''</div><h1>'''+headline+'''</h1><div class="rule"></div><div class="body">'''+body+'''</div>'''+('<div class="case">'+esc(title)+'</div>' if i==0 else '')+'''</section><div class="bottom"><span>본 콘텐츠는 풍자 목적의 창작물입니다.</span><span>'''+f'{i+1:02d} / {n:02d}'+'''</span></div></main></body></html>'''


def make_figma_cover(s, title):
    from pathlib import Path
    import base64
    import html

    esc = lambda x: html.escape(str(x or ''))

    background = Path("/opt/unreal-github/figma_assets/cover_background.png")
    logo = Path("/opt/unreal-github/figma_assets/logo_symbol.svg")

    bg64 = base64.b64encode(background.read_bytes()).decode()
    logo64 = base64.b64encode(logo.read_bytes()).decode()

    eyebrow = esc(s.get("eyebrow", "비현실문제해결부 심의 기록"))
    headline = esc(s.get("headline", title)).replace("\\n", "<br>")

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; }}

body {{
    margin: 0;
    width: 1080px;
    height: 1350px;
    overflow: hidden;
    background: #111820;
    color: white;
    font-family: 'ROKG', 'Noto Sans KR', sans-serif;
}}

.background {{
    position: absolute;
    inset: -80px;
    background-image: url('data:image/png;base64,{bg64}');
    background-position: center;
    background-size: cover;
    filter: blur(25px);
}}

.overlay {{
    position: absolute;
    inset: 0;
    background: linear-gradient(
        180deg,
        rgba(0,0,0,.18) 0%,
        rgba(0,0,0,.36) 40%,
        rgba(0,0,0,.55) 100%
    );
}}

.logo {{
    position: absolute;
    left: 64px;
    top: 61px;
    display: flex;
    align-items: center;
    gap: 15px;
}}

.logo img {{
    width: 46px;
    height: 52px;
}}

.logo span {{
    font-size: 24px;
    font-weight: 600;
}}

.case-number {{
    position: absolute;
    right: 70px;
    top: 79px;
    font-size: 21px;
}}

.top-line {{
    position: absolute;
    left: 63px;
    top: 128px;
    width: 947px;
    height: 1px;
    background: rgba(255,255,255,.8);
}}

.eyebrow {{
    position: absolute;
    left: 63px;
    top: 245px;
    width: 947px;
    font-size: 43px;
    line-height: 1.35;
    word-break: keep-all;
}}

.headline {{
    position: absolute;
    left: 63px;
    top: 329px;
    width: 947px;
    font-size: 76px;
    line-height: 1.3;
    letter-spacing: -2px;
    word-break: keep-all;
}}
</style>
</head>
<body>
<div class="background"></div>
<div class="overlay"></div>

<div class="logo">
    <img src="data:image/svg+xml;base64,{logo64}">
    <span>비현실문제해결부</span>
</div>

<div class="case-number">사건번호 제 2026-1024호</div>
<div class="top-line"></div>

<div class="eyebrow">{eyebrow}</div>
<div class="headline">{headline}</div>
</body>
</html>"""

async def _render(draft, prefix):
    pfx=Path(prefix); pfx.parent.mkdir(parents=True,exist_ok=True); paths=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage'])
        page=await browser.new_page(viewport={'width':WIDTH,'height':HEIGHT},device_scale_factor=1)
        for i,s in enumerate(draft['slides']):
            await page.set_content((make_figma_cover(s, draft.get('title', '비현실문제해결부')) if i == 0 else make_html(s,i,len(draft['slides']),draft.get('title','비현실문제부 심의 기록'))))
            path=str(pfx.parent/(pfx.name+f'_{i+1:02d}.png'))
            await page.screenshot(path=path,type='png'); paths.append(path)
        await browser.close()
    return paths

def render_carousel(draft, output_prefix):
    return asyncio.run(_render(draft,output_prefix))
