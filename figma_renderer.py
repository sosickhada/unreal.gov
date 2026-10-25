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


# Fixed slides use a single approved image each. Never replace these with
# search results or AI-generated imagery.
FIXED_SLIDE_IMAGES = {
    2: Path("/opt/unreal-github/figma_assets/resolution_fixed.png"),
    3: Path("/opt/unreal-github/figma_assets/ending_fixed.png"),
}


def make_fixed_slide(image_path):
    import base64
    if not image_path.is_file():
        raise FileNotFoundError(
            f"Fixed Figma slide asset missing: {image_path}. "
            "Export the approved Figma frame to this path before rendering."
        )
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return (
        '<!doctype html><html lang="ko"><meta charset="utf-8">'
        '<style>*{box-sizing:border-box}html,body{margin:0;width:1080px;'
        'height:1350px;overflow:hidden;background:#061225}'
        'img{display:block;width:1080px;height:1350px;object-fit:fill}</style>'
        f'<img src="data:image/png;base64,{encoded}"></html>'
    )


def make_figma_content(s, title):
    """Slide 2: editable text on the original Figma composition."""
    from pathlib import Path
    from html import escape
    import re
    root = Path("/opt/unreal-github/figma_assets")
    image_path = s.get("background_image") or str(root / "content_background.png")
    background = Path(image_path)
    if not background.is_file():
        raise FileNotFoundError(f"Slide 2 background missing: {background}")
    bg = background.resolve().as_uri()
    font = (root / "fonts/ROKG_R.ttf").resolve().as_uri()
    logo = (root / "cover_logo_exact.svg").resolve().as_uri()
    extras = ""
    for name,x,y,w,h in [
        ("logo_ellipse10.svg",61,66,51,51),
        ("logo_vector7.svg",92.75,61.5,16.049,13.039),
        ("logo_vector6.svg",62.45,59.47,14.183,15.034),
    ]:
        encoded = (root/name).resolve().as_uri()
        extras += f'<img style="position:absolute;left:{x}px;top:{y}px;width:{w}px;height:{h}px" src="{encoded}">'
    candidates = [root/"fonts/ChosunNm.ttf", root/"fonts/ChosunilboNM.ttf", root/"fonts/ChosunilboNM.otf", root/"ChosunilboNM.ttf"]
    chosun = next((f for f in candidates if f.is_file()), None)
    if chosun is None:
        raise FileNotFoundError("ChosunilboNM font missing in figma_assets/fonts")
    chosun64 = chosun.resolve().as_uri()
    eyebrow = escape(str(s.get("eyebrow") or "민원 접수 유형"))
    raw = str(s.get("body") or s.get("headline") or "")
    emphasis = s.get("emphasis", [])
    if isinstance(emphasis, str): emphasis = [emphasis]
    terms = sorted({str(t) for t in emphasis if t and str(t) in raw}, key=len, reverse=True)
    parts = re.split("(" + "|".join(re.escape(t) for t in terms) + ")", raw) if terms else [raw]
    body = "".join('<span class="emphasis">' + escape(t) + '</span>' if t in terms else escape(t) for t in parts)
    case = escape(str(s.get("case_number") or "사건번호 제 2026-1024호"))
    return f"""<!doctype html><html lang="ko"><meta charset="utf-8">
<style>
@font-face{{font-family:ROKG;src:url("{font}")}}\n@font-face{{font-family:ChosunilboNM;src:url("{chosun64}") format("truetype");font-weight:400;font-style:normal;font-display:block}}
*{{box-sizing:border-box}}body{{margin:0;width:1080px;height:1350px;overflow:hidden;background:#101923;color:white}}
.bg{{position:absolute;left:-496px;top:-90px;width:1977px;height:1483px;background:url("{bg}") center/cover no-repeat}}
.bottom-blur{{position:absolute;left:0;top:560px;width:1080px;height:790px;backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);mask-image:linear-gradient(to bottom,transparent,black 80%);-webkit-mask-image:linear-gradient(to bottom,transparent,black 80%)}}\n.shade{{position:absolute;left:0;top:540px;width:1080px;height:810px;background:linear-gradient(to bottom,transparent,rgba(5,28,61,.46) 38%,rgba(3,18,45,.94) 100%)}}
.line{{position:absolute;left:63px;top:128px;width:947px;height:1px;background:rgba(255,255,255,.8)}}
.case{{position:absolute;right:65px;top:75px;font:21px/1.4 ROKG;white-space:nowrap}}
.eyebrow{{position:absolute;left:102px;top:783px;font:52.953px/1.15 ROKG;letter-spacing:-1.06px}}
.under{{position:absolute;left:103px;top:939px;width:292px;height:5px;background:white}}
.body{{position:absolute;left:102px;top:897px;width:874px;font:32.283px/1.85 ChosunilboNM,serif;letter-spacing:-.97px;white-space:pre-wrap;word-break:keep-all}}
.emphasis{{position:relative;white-space:normal}}\n.emphasis::after{{content:"";position:absolute;left:0;right:0;top:52%;height:0;border-top:5px solid rgba(255,255,255,.95);transform:rotate(-1deg);pointer-events:none}}\n.logo{{position:absolute;left:64px;top:61px;width:45.487px;height:51.744px}}
.logotext{{position:absolute;left:124px;top:78.63px;font:24.207px ROKG;white-space:nowrap}}
</style><body><div class="bg"></div><div class="bottom-blur"></div><div class="shade"></div><div class="line"></div>
{extras}<img class="logo" src="{logo}"><div class="logotext">비현실문제해결부</div>
<div class="case">{case}</div><div class="eyebrow">{eyebrow}</div><div class="body">{body}</div></body></html>"""


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
        raise FileNotFoundError("Figma logo symbol asset missing: " + str(logo))
    logo64 = base64.b64encode(logo.read_bytes()).decode()
    extra_logo_assets = [
        ("logo_ellipse10.svg", 61, 66, 51, 51),
        ("logo_vector7.svg", 92.75, 61.5, 16.049, 13.039),
        ("logo_vector6.svg", 62.45, 59.47, 14.183, 15.034),
    ]
    extra_logo_html = ""
    for filename, x, y, width, height in extra_logo_assets:
        asset = logo.parent / filename
        if not asset.is_file():
            raise FileNotFoundError("Figma logo layer missing: " + str(asset))
        encoded = base64.b64encode(asset.read_bytes()).decode()
        extra_logo_html += (
            f'<img class="logo-extra" src="data:image/svg+xml;base64,{encoded}" '
            f'style="left:{x}px;top:{y}px;width:{width}px;height:{height}px">'
        )


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

.logo-extra {{
    position: absolute;
    display: block;
    object-fit: fill;
    filter: none;
}}
.logo-symbol {{
    position: absolute;
    left: 64px;
    top: 61px;
    width: 45.487px;
    height: 51.744px;
}}
.logo-symbol img {{
    display: block;
    width: 100%;
    height: 100%;
    filter: none;
}}
.logo-text {{
    position: absolute;
    left: 124px;
    top: 78.63px;
    font-family: 'ROKG', sans-serif;
    font-size: 24.207px;
    line-height: normal;
    color: white;
    white-space: nowrap;
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
.headline {{ z-index: 3; }}
</style>
</head>
<body>
<div class="background"></div>
<div class="top-blur"></div>
<div class="overlay"></div>

{extra_logo_html}
<div class="logo-symbol"><img src="data:image/svg+xml;base64,{logo64}"></div>\n<div class="logo-text">비현실문제해결부</div>

<div class="case-number">사건번호 제 2026-1024호</div>
<div class="top-line"></div>

<div class="eyebrow">{eyebrow}</div>
<div class="quote open">“</div>
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
                    markup = (
                        make_figma_cover(slide, draft.get('title', '비현실문제해결부'))
                        if i == 0 else
                        make_figma_content(slide, draft.get('title', '비현실문제해결부'))
                        if i == 1 else
                        make_fixed_slide(FIXED_SLIDE_IMAGES[i])
                        if i in FIXED_SLIDE_IMAGES else
                        make_html(slide, i, len(draft['slides']),
                                  draft.get('title', '비현실문제부 심의 기록'))
                    )
                    if i == 1:
                        # file:// HTML can load adjacent local image/font assets.
                        # about:blank + set_content cannot reliably load file:// URLs.
                        with tempfile.NamedTemporaryFile(
                            mode='w', suffix='.html', encoding='utf-8',
                            dir='/opt/unreal-github/figma_assets', delete=False
                        ) as temp_html:
                            temp_html.write(markup)
                            html_path = Path(temp_html.name)
                        try:
                            await page.goto(html_path.as_uri(), wait_until='load', timeout=45000)
                        finally:
                            html_path.unlink(missing_ok=True)
                    else:
                        await page.set_content(markup, wait_until='load', timeout=45000)
                    await page.evaluate('document.fonts.ready')
                    if i == 1:
                        font_status = await page.evaluate('''async () => { await document.fonts.load('32px ChosunilboNM', '퇴근 방해 및 용어 왜곡'); return {loaded: document.fonts.check('32px ChosunilboNM', '퇴근 방해 및 용어 왜곡'), status: document.fonts.status}; }''')
                        if not font_status['loaded']:
                            raise RuntimeError(f'ChosunilboNM font failed to load: {font_status}')
                    path = str(pfx.parent / (pfx.name + f'_{i+1:02d}.png'))
                    await page.screenshot(path=path, type='png', timeout=45000)
                    paths.append(path)
            finally:
                await context.close()
    return paths

def render_carousel(draft, output_prefix):
    return asyncio.run(_render(draft,output_prefix))
