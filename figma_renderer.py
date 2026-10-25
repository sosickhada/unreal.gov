from pathlib import Path
import asyncio, html
import tempfile
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
    logo = Path("/opt/unreal-github/figma_assets/cover_logo_exact.svg")

    image_path = s.get("background_image")
    if image_path:
        candidate = Path(image_path).expanduser().resolve()
        if not candidate.is_file() or candidate.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise ValueError("background_image must point to a PNG, JPG, or WebP file")
        background = candidate
    mime = "image/png" if background.suffix.lower() == ".png" else ("image/webp" if background.suffix.lower() == ".webp" else "image/jpeg")
    bg64 = base64.b64encode(background.read_bytes()).decode()
    if not logo.is_file():
        raise FileNotFoundError("Figma cover logo asset missing: " + str(logo))
    logo64 = base64.b64encode(logo.read_bytes()).decode()

    font_dir = Path("/opt/unreal-github/figma_assets/fonts")
    rokg64 = base64.b64encode(
        (font_dir / "ROKG_R.ttf").read_bytes()
    ).decode()


    eyebrow = esc(s.get("eyebrow", "비현실문제해결부 심의 기록"))
    headline = esc(s.get("headline", title)).replace("\\n", "<br>")

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<style>
@font-face {{
    font-family: 'ROKG';
    src: url('data:font/ttf;base64,{rokg64}') format('truetype');
    font-weight: 400;
}}



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
    inset: -5px;
    background-image: url('data:{mime};base64,{bg64}');
    background-position: center;
    background-size: cover;
    filter: none;
}}

.overlay {{
    position: absolute;
    inset: 0;
    background: linear-gradient(
        180deg,
        rgba(3,13,29,.92) 0%,
        rgba(4,17,36,.82) 24%,
        rgba(5,19,38,.42) 47%,
        rgba(4,15,31,.08) 75%,
        rgba(4,15,31,.04) 100%
    );
}}
.top-blur {{
    position: absolute;
    inset: 0;
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    mask-image: linear-gradient(to bottom, black 0%, black 14%, transparent 49%);
    -webkit-mask-image: linear-gradient(to bottom, black 0%, black 14%, transparent 49%);
    pointer-events: none;
}}

.logo {{
    position: absolute;
    left: 64px;
    top: 61px;
    display: flex;
    align-items: center;
    gap: 15px;
    height: 52px;
}}

.logo img {{
    width: 46px;
    height: 52px;
    object-fit: contain;
    filter: none;
}}

.logo span {{
    font-size: 24px;
    font-weight: 600;
    line-height: 1;
    white-space: nowrap;
    display: flex;
    align-items: center;
    height: 52px;
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
.quote {{
    position: absolute;
    width: 188px;
    height: 208.563px;
    font-family: 'ROKG', sans-serif;
    font-size: 376px;
    line-height: 1.4;
    color: rgba(255,255,255,.20);
    pointer-events: none;
    z-index: 2;
    white-space: nowrap;
}}
.quote.open {{
    left: 17px;
    top: 226px;
    text-align: right;
}}
.quote.close {{
    left: 681px;
    top: 609.5625px;
    text-align: right;
    transform: rotate(180deg);
    transform-origin: center center;
}}
.headline {{ z-index: 3; }}
</style>
</head>
<body>
<div class="background"></div>
<div class="top-blur"></div>
<div class="overlay"></div>

<div class="logo">
    <img src="data:image/svg+xml;base64,{logo64}">
    <span>비현실문제해결부</span>
</div>

<div class="case-number">사건번호 제 2026-1024호</div>
<div class="top-line"></div>

<div class="eyebrow">{eyebrow}</div>
<div class="quote open">“</div>
<div class="quote close">“</div>
<div class="headline">{headline}</div>
</body>
</html>"""

async def _render(draft, prefix):
    pfx=Path(prefix); pfx.parent.mkdir(parents=True,exist_ok=True); paths=[]
    async with async_playwright() as p:
        # Keep the browser profile in RAM to avoid slow disk I/O on the VM.
        # TemporaryDirectory removes it after rendering (including on errors).
        with tempfile.TemporaryDirectory(prefix='unreal-render-', dir='/dev/shm') as profile:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=profile,
                headless=True,
                viewport={'width': WIDTH, 'height': HEIGHT},
                device_scale_factor=1,
                timeout=45000,
                args=['--no-sandbox', '--disable-dev-shm-usage',
                      '--disable-gpu', '--disable-extensions',
                      '--disable-background-networking', '--no-first-run'],
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                for i, slide in enumerate(draft['slides']):
                    markup = (make_figma_cover(slide, draft.get('title', '비현실문제해결부'))
                              if i == 0 else make_html(slide, i, len(draft['slides']),
                                                      draft.get('title', '비현실문제부 심의 기록')))
                    await page.set_content(markup, wait_until='load', timeout=45000)
                    await page.evaluate('document.fonts.ready')
                    path = str(pfx.parent / (pfx.name + f'_{i+1:02d}.png'))
                    await page.screenshot(path=path, type='png', timeout=45000)
                    paths.append(path)
            finally:
                await context.close()
    return paths

def render_carousel(draft, output_prefix):
    return asyncio.run(_render(draft,output_prefix))
