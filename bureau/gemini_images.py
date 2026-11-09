"""Gemini images: conservative, persistent spending reservations; no implicit retries.

Reserved KRW is an application estimate, NOT a provider billing cap.
"""
import base64
import datetime as dt
import json
import time
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from .store import Store, now, digest
from .images import inspect_image, SLOTS
from .generated_images import scene_prompt

DEFAULT_MODEL='gemini-nano-banana-2.1'
MAX_INPUT_BYTES=4096
TERMS='https://ai.google.dev/gemini-api/terms'

class GeminiBlocked(ValueError):
    pass


def migrate(c):
    c.execute('''CREATE TABLE IF NOT EXISTS gemini_image_requests(
        request_key TEXT PRIMARY KEY, model TEXT NOT NULL, state TEXT NOT NULL,
        result TEXT, created_at TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS gemini_image_attempts(
        id INTEGER PRIMARY KEY,request_key TEXT NOT NULL,attempt INTEGER NOT NULL,
        period TEXT NOT NULL,day TEXT NOT NULL,reserved_krw INTEGER NOT NULL,
        state TEXT NOT NULL,price_snapshot TEXT NOT NULL,usage TEXT,
        observed_estimate_krw INTEGER,error_code TEXT,created_at TEXT NOT NULL,
        UNIQUE(request_key,attempt))''')
    c.execute('''CREATE TABLE IF NOT EXISTS gemini_image_periods(
        period TEXT PRIMARY KEY,halted INTEGER NOT NULL DEFAULT 0,reason TEXT)''')


def clock_period(at=None):
    local=(at or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo('Asia/Seoul'))
    return local.strftime('%Y-%m'),local.date().isoformat()


def pricing(config,at=None):
    try:
        path=Path(config.env.get('GEMINI_IMAGE_PRICING_FILE') or Path(__file__).resolve().parents[1]/'config/gemini_image_pricing.json')
        data=json.loads(path.read_text()); today=(at or dt.datetime.now(dt.timezone.utc)).date()
        verified=dt.date.fromisoformat(data['verified_on']);until=dt.date.fromisoformat(data['valid_until'])
        if not verified<=today<=until or (until-verified).days>31 or data['currency']!='USD' or data['billing_mode']!='standard': raise ValueError()
        model=config.env.get('GEMINI_IMAGE_MODEL',DEFAULT_MODEL);rate=data['models'][model]
        import re
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,100}',model): raise ValueError()
        if rate['image_size']!='2K' or rate['max_output_tokens']!=4096: raise ValueError()
        for k in ('input_per_million','text_output_per_million','image_output_per_million','image_usd'):
            value=Decimal(rate[k])
            if not value.is_finite() or value<=0: raise ValueError()
        fx=Decimal(config.env.get('GEMINI_IMAGE_USD_KRW','1800'))
        margin=Decimal(config.env.get('GEMINI_IMAGE_COST_MARGIN','1.25'))
        if not fx.is_finite() or not margin.is_finite() or not Decimal('1500')<=fx<=10000 or not Decimal('1.1')<=margin<=3: raise ValueError()
        budget=int(config.env.get('GEMINI_IMAGE_MONTHLY_BUDGET_KRW','5000'))
        daily=int(config.env.get('GEMINI_IMAGE_MAX_GENERATIONS_PER_DAY','2'))
        retries=int(config.env.get('GEMINI_IMAGE_MAX_RETRIES','1'))
        if not 0<budget<=5000 or not 0<=daily<=2 or not 0<=retries<=1: raise ValueError()
        # Byte-bound input (no billed countTokens call). Reserve the entire output
        # cap at the most expensive modality PLUS one documented 2K image. This
        # deliberately over-reserves even if all output is covered by that cap.
        usd=(Decimal(MAX_INPUT_BYTES+64)*Decimal(rate['input_per_million'])+
             Decimal(4096)*max(Decimal(rate['text_output_per_million']),Decimal(rate['image_output_per_million'])))/1000000+Decimal(rate['image_usd'])
        ceiling=int((usd*fx*margin).to_integral_value(rounding=ROUND_CEILING))
        return dict(model=model,rate=rate,fx=str(fx),margin=str(margin),ceiling_krw=ceiling,
                    reserved_usd=str(usd),budget=budget,daily=daily,retries=retries,verified_on=data['verified_on'],source=data['source'])
    except (ValueError,KeyError,TypeError,OSError,ArithmeticError):
        raise GeminiBlocked('Gemini 가격·환율·한도 정보가 없거나 유효하지 않아 호출을 차단했습니다.') from None


def settings(config,at=None):
    if config.env.get('GEMINI_IMAGE_ENABLED')!='1': raise GeminiBlocked('GEMINI_IMAGE_ENABLED=0: 실제 생성은 승인 후 활성화하세요.')
    if not config.env.get('GEMINI_API_KEY'): raise GeminiBlocked('GEMINI_API_KEY 설정이 필요합니다.')
    config.require_external()
    return pricing(config,at)


def prompt_for(draft,slot):
    if slot not in SLOTS: raise GeminiBlocked('Unknown image slot')
    camera=('Medium wide establishing scene at eye level, show the everyday conflict through objects.' if slot=='content' else
            'Different scene and camera angle: close detail of the consequence and key object, no repeat of the establishing view.')
    # Caption/card text is deliberately excluded. Story context is untrusted data.
    context={'event_topic':draft.get('title','')[:100], 'visual_brief':draft.get('image_brief',{}).get(slot,{})}
    prompt=('Create ONE photorealistic editorial documentary image of an ordinary Korean daily-life space. '
            'A fictional illustrative scene, never evidence of a real incident. Natural ambient light, modest saturation, '
            'realistic texture and perspective, no advertising aesthetic. '+scene_prompt(draft,slot)+' '+camera+
            ' Keep subtle emotions through posture or objects, no identifiable real people. Do not render any words from the following context. '
            'Context data: '+json.dumps(context,ensure_ascii=False))
    if len(prompt.encode())>MAX_INPUT_BYTES: raise GeminiBlocked('Image prompt exceeds the reserved input bound')
    return prompt


def request_body(prompt,quote):
    return {'contents':[{'role':'user','parts':[{'text':prompt}]}],
            'generationConfig':{'candidateCount':1,'responseModalities':['IMAGE'],
                'maxOutputTokens':4096,'thinkingConfig':{'thinkingLevel':'minimal'},
                'imageConfig':{'aspectRatio':'4:5','imageSize':quote['rate']['image_size']}}}


def status(config,store=None,at=None):
    store=store or Store(config.db);q=pricing(config,at);month,day=clock_period(at)
    with store.tx() as c:
        used=c.execute('SELECT COALESCE(sum(reserved_krw),0) FROM gemini_image_attempts WHERE period=?',(month,)).fetchone()[0]
        count=c.execute('SELECT count(*) FROM gemini_image_attempts WHERE day=?',(day,)).fetchone()[0]
        halted=c.execute('SELECT halted FROM gemini_image_periods WHERE period=?',(month,)).fetchone()
        totals=c.execute("SELECT count(*),COALESCE(sum(observed_estimate_krw),0),count(usage),COALESCE(sum(state='succeeded'),0),COALESCE(sum(state IN ('reserved','sent','uncertain')),0) FROM gemini_image_attempts WHERE period=?",(month,)).fetchone()
    return {'period_kst':month,'day_kst':day,'monthly_budget_krw':q['budget'],'reserved_krw':used,
            'remaining_krw':max(0,q['budget']-used),'monthly_attempts':totals[0],'usage_records':totals[2],
            'observed_estimate_krw':totals[1],'successful_generations':totals[3],'uncertain_attempts':totals[4],'remaining_attempts_today':max(0,q['daily']-count),
            'remaining_generations':0 if halted and halted[0] else max(0,min(q['daily']-count,(q['budget']-used)//q['ceiling_krw'])),
            'reservation_per_attempt_krw':q['ceiling_krw'],'enabled':config.env.get('GEMINI_IMAGE_ENABLED')=='1',
            'key_present':bool(config.env.get('GEMINI_API_KEY')),'actual_bill_available':False}


class GeminiImages:
    def __init__(self,config,http=requests,at=None):
        self.config=config;self.store=Store(config.db);self.http=http;self.at=at

    def reserve(self,key,q):
        month,day=clock_period(self.at);blocked=None;result=None
        with self.store.tx() as c:
            old=c.execute('SELECT * FROM gemini_image_requests WHERE request_key=?',(key,)).fetchone()
            last=c.execute('SELECT * FROM gemini_image_attempts WHERE request_key=? ORDER BY attempt DESC LIMIT 1',(key,)).fetchone()
            if old and old['state']=='succeeded': return {'cached':json.loads(old['result'])}
            if last and last['state'] in ('reserved','sent','uncertain'):
                raise GeminiBlocked('이전 Gemini 호출 결과가 불확실합니다. 자동 재호출하지 않습니다.')
            attempt=last['attempt']+1 if last else 0
            if attempt>q['retries']: raise GeminiBlocked('이미지별 재시도 한도에 도달했습니다.')
            c.execute('INSERT OR IGNORE INTO gemini_image_periods(period) VALUES(?)',(month,))
            used=c.execute('SELECT COALESCE(sum(reserved_krw),0) FROM gemini_image_attempts WHERE period=?',(month,)).fetchone()[0]
            count=c.execute('SELECT count(*) FROM gemini_image_attempts WHERE day=?',(day,)).fetchone()[0]
            halted=c.execute('SELECT halted FROM gemini_image_periods WHERE period=?',(month,)).fetchone()[0]
            if halted or used+q['ceiling_krw']>q['budget']:
                blocked='이번 달 Gemini 이미지 예산이 부족합니다. Pixabay 또는 수동 사진을 선택하세요.'
                c.execute('UPDATE gemini_image_periods SET halted=1,reason=? WHERE period=?',('insufficient_headroom',month))
                self.store.notify(c,'gemini-budget-stop:'+month,{'text':blocked+' 예약액은 실제 청구액이 아닌 보수적 추정입니다.'})
            elif count>=q['daily']: blocked='오늘 Gemini 이미지 생성 호출 한도(재시도 포함)에 도달했습니다.'
            else:
                c.execute("INSERT OR IGNORE INTO gemini_image_requests VALUES(?,?,'pending',NULL,?)",(key,q['model'],now()))
                aid=c.execute("INSERT INTO gemini_image_attempts(request_key,attempt,period,day,reserved_krw,state,price_snapshot,created_at) VALUES(?,?,?,?,?,'reserved',?,?)",(key,attempt,month,day,q['ceiling_krw'],json.dumps(q),now())).lastrowid
                used+=q['ceiling_krw']
                if used*5>=q['budget']*4:
                    self.store.notify(c,'gemini-budget-80:'+month,{'text':f'Gemini 이미지 월 예산 80% 도달: 보수적 예약액 {used}/{q["budget"]}원. 실제 청구액은 별도 확인하세요.'})
                if used>=q['budget']:
                    c.execute('UPDATE gemini_image_periods SET halted=1,reason=? WHERE period=?',('limit',month))
                    self.store.notify(c,'gemini-budget-stop:'+month,{'text':'Gemini 월 예산 100% 도달: 다음 생성은 차단합니다.'})
                result={'id':aid,'attempt':attempt}
        if blocked: raise GeminiBlocked(blocked)
        return result

    def finish(self,aid,state,code=None,usage=None,result=None):
        with self.store.tx() as c:
            row=c.execute('SELECT * FROM gemini_image_attempts WHERE id=?',(aid,)).fetchone()
            c.execute('UPDATE gemini_image_attempts SET state=?,error_code=?,usage=? WHERE id=?',(state,code,json.dumps(usage) if usage is not None else None,aid))
            if result:
                c.execute("UPDATE gemini_image_requests SET state='succeeded',result=? WHERE request_key=?",(json.dumps(result),row['request_key']))
            else: c.execute('UPDATE gemini_image_requests SET state=? WHERE request_key=?',(state,row['request_key']))
            # No automatic release, even for failed/rejected calls. Modality counts
            # are provider-observed usage, never an invoice or a cost guarantee.
            if isinstance(usage,dict):
                counts=[usage.get('promptTokenCount'),usage.get('candidatesTokenCount'),usage.get('thoughtsTokenCount',0)]
                if all(type(v) is int and v>=0 for v in counts):
                    q=json.loads(row['price_snapshot']);rate=q['rate']
                    usd=(Decimal(counts[0])*Decimal(rate['input_per_million'])+Decimal(counts[1]+counts[2])*max(Decimal(rate['image_output_per_million']),Decimal(rate['text_output_per_million'])))/1000000
                    observed=int((usd*Decimal(q['fx'])*Decimal(q['margin'])).to_integral_value(rounding=ROUND_CEILING))
                    c.execute('UPDATE gemini_image_attempts SET observed_estimate_krw=? WHERE id=?',(observed,aid))
                    if observed>row['reserved_krw']:
                        c.execute('UPDATE gemini_image_attempts SET reserved_krw=? WHERE id=?',(observed,aid))
                        c.execute('UPDATE gemini_image_periods SET halted=1,reason=? WHERE period=?',('usage_exceeded_reservation',row['period']))
                        self.store.notify(c,'gemini-usage-overrun:'+row['period'],{'text':'Gemini 사용량이 예약 가정을 초과했습니다. 이번 달 생성을 중단하고 가격/청구 내역을 확인하세요.'})

    def generate(self,draft,slot,variant='0'):
        q=settings(self.config,self.at);prompt=prompt_for(draft,slot);body=request_body(prompt,q)
        key=digest({'provider':'gemini','request':body,'model':q['model'],'slot':slot,'variant':str(variant)})
        for _ in range(q['retries']+1):
            reserved=self.reserve(key,q)
            if 'cached' in reserved:
                cached=reserved['cached']
                try:
                    if inspect_image(Path(cached['path']).read_bytes())['sha256']!=cached['sha256']: raise ValueError()
                except (OSError,ValueError): raise GeminiBlocked('캐시 이미지가 없거나 변경되었습니다. 별도 재생성 요청이 필요합니다.') from None
                return cached
            aid=reserved['id']
            with self.store.tx() as c: c.execute("UPDATE gemini_image_attempts SET state='sent' WHERE id=?",(aid,))
            started=time.monotonic()
            try:
                response=self.http.post('https://generativelanguage.googleapis.com/v1beta/models/'+q['model']+':generateContent',
                    headers={'x-goog-api-key':self.config.env['GEMINI_API_KEY'],'Content-Type':'application/json'},
                    json=body,timeout=(10,100),allow_redirects=False,stream=True)
                try:
                    if response.status_code!=200:
                        code='http_'+str(response.status_code)
                        self.finish(aid,'failed',code)
                        if response.status_code==429 and reserved['attempt']<q['retries']: continue
                        if response.status_code==429:
                            raise GeminiBlocked('Gemini 이미지 생성이 제한되었습니다 (HTTP 429). 할당량 또는 결제 상태 확인 필요: Google AI Studio에서 해당 API 키 프로젝트의 유료 티어·이미지 생성 할당량·사용량을 확인하세요. 429만으로 결제 미연결과 일시적인 속도 제한을 구분할 수 없습니다. 비용 예약은 유지합니다.')
                        raise GeminiBlocked('Gemini API 요청을 처리하지 못했습니다 ('+code+'). 자동 환급하지 않습니다.')
                    data=bytearray()
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if time.monotonic()-started>120: raise ValueError('Response time limit')
                        if len(data)>35_000_000: raise ValueError('Response too large')
                    payload=json.loads(data)
                finally: response.close()
            except GeminiBlocked: raise
            except Exception:
                self.finish(aid,'uncertain','transport_or_response_unknown')
                raise GeminiBlocked('Gemini 호출 결과가 불확실합니다. 비용 예약을 유지하고 재호출을 차단합니다.') from None
            if not isinstance(payload,dict):
                self.finish(aid,'rejected','invalid_response_shape')
                raise GeminiBlocked('Gemini 응답 형식을 확인하지 못했습니다.')
            usage=payload.get('usageMetadata')
            try:
                candidates=payload.get('candidates',[])
                if len(candidates)!=1 or candidates[0].get('finishReason')!='STOP': raise ValueError()
                parts=candidates[0].get('content',{}).get('parts',[])
                images=[part['inlineData'] for part in parts if 'inlineData' in part and not part.get('thought')]
                if len(images)!=1 or images[0].get('mimeType') not in ('image/png','image/jpeg','image/webp'): raise ValueError()
                content=base64.b64decode(images[0]['data'],validate=True);metadata=inspect_image(content)
                path=Path(self.config.db).parent/'data/gemini-images'/(key+'.png')
                path.parent.mkdir(parents=True,exist_ok=True)
                # Extension describes actual bytes, no EXIF/SynthID manipulation.
                from PIL import Image
                from io import BytesIO
                with Image.open(BytesIO(content)) as im:
                    if Image.MIME[im.format]!=images[0]['mimeType']: raise ValueError('MIME mismatch')
                    extension={'JPEG':'.jpg','PNG':'.png','WEBP':'.webp'}[im.format]
                path=path.with_suffix(extension);pending=path.with_suffix(extension+'.pending');pending.write_bytes(content);pending.replace(path)
                result=dict(metadata,available=True,path=str(path.resolve()),provider='gemini',ai_generated=True,
                    model=q['model'],request_key=key,prompt=prompt,slot=slot,variant=str(variant),
                    quality_status='technical_pass_human_review_required',review_required=True,license_verified=False,
                    source_url='https://ai.google.dev/gemini-api/docs/models/'+q['model'],license_url=TERMS,
                    license='Google Gemini API terms; generated illustration; third-party rights require review')
            except (ValueError,KeyError,TypeError,OSError):
                self.finish(aid,'rejected','image_validation_failed',usage)
                if reserved['attempt']<q['retries']: continue
                raise GeminiBlocked('Gemini 이미지가 형식·해상도·선명도 검사를 통과하지 못했습니다.') from None
            self.finish(aid,'succeeded',usage=usage,result=result)
            return result
        raise GeminiBlocked('Gemini 이미지 재시도 한도에 도달했습니다.')


def schedule(store,config,rid,revision,slot,variant='0'):
    settings(config)
    if slot not in SLOTS or (str(variant)!='0' and not str(variant).isdigit()): raise GeminiBlocked('Invalid image generation request')
    with store.tx() as c:
        row=c.execute("SELECT status,revision FROM selections WHERE id=?",(rid,)).fetchone()
        if not row or row['revision']!=revision or row['status']!='draft_ready': raise GeminiBlocked('현재 기획 승인 버전에서만 이미지를 생성할 수 있습니다.')
        render=c.execute("SELECT id FROM jobs WHERE kind='render' AND json_extract(payload,'$.id')=? AND json_extract(payload,'$.revision')=? AND state='waiting'",(rid,revision)).fetchone()
        if not render: raise GeminiBlocked('사진 검토 대기 단계에서 요청하세요.')
        if str(variant)!='0':
            prior=c.execute("SELECT cp.result FROM checkpoints cp JOIN jobs j ON j.id=cp.job_id WHERE cp.rowid=? AND cp.state='succeeded' AND j.kind IN ('render','gemini_image') AND json_extract(j.payload,'$.id')=? AND json_extract(j.payload,'$.revision')=?",(int(variant),rid,revision)).fetchone()
            if not prior: raise GeminiBlocked('이전 이미지가 만료되었습니다.')
            image=json.loads(prior[0])
            if image.get('provider')!='gemini' or image.get('slot')!=slot: raise GeminiBlocked('Unknown Gemini image')
        jid=store.enqueue(c,f'gemini-request:{rid}:{revision}:{slot}:{variant}','gemini_image',{'id':rid,'revision':revision,'slot':slot,'variant':str(variant)})
        # A later explicit click can resume a quota-blocked job after day/month
        # rollover. The provider ledger still refuses uncertain/duplicate calls.
        c.execute("UPDATE jobs SET state='queued',error_code=NULL WHERE id=? AND state='waiting' AND error_code='gemini_image_blocked'",(jid,))
        return jid


def budget_message(config,store):
    data=status(config,store)
    active='활성' if data['enabled'] and data['key_present'] else '비활성 또는 키 설정 필요'
    return (f"Gemini 이미지 · {data['period_kst']} KST · {active}\n"
            f"월 예산 {data['monthly_budget_krw']:,}원 / 보수적 예약 {data['reserved_krw']:,}원\n"
            f"남은 예산 {data['remaining_krw']:,}원 / 오늘 남은 호출 {data['remaining_attempts_today']}회\n"
            f"현재 예산으로 오늘 추가 예약 가능 {data['remaining_generations']}회\n"
            f"1회 최대 예약 {data['reservation_per_attempt_krw']}원, 재시도도 별도 차감\n"
            "애플리케이션 추정이며 Google 실제 청구액 보장은 아닙니다.")
