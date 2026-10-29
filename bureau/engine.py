import json
import datetime as dt
from zoneinfo import ZoneInfo
from .store import now, kst_day, Store
from .preflight import ConfigurationError
from .content import fetch_news, candidate_prompt, draft_prompt, parse_json, validate_candidates, validate_draft, draft_quality, distinct_news, NewsFailure


class Uncertain(RuntimeError):
    pass


class Waiting(RuntimeError):
    def __init__(self,message,code='requirements_missing'):
        super().__init__(message);self.code=code


class Engine:
    def __init__(self, config, claude=None, media=None, telegram=None, instagram=None, news=None):
        from .adapters import Claude, Media, Telegram
        from .instagram import Instagram
        self.config=config; self.store=Store(config.db)
        self.claude=claude or Claude(config); self.media=media or Media(config)
        self.telegram=telegram or Telegram(config); self.instagram=instagram or Instagram(config)
        self.news=news or (lambda:fetch_news(hours=self.config.integer('NEWS_MAX_AGE_HOURS',72)))

    def step(self, job, name, call, ambiguous=False, paid=False):
        with self.store.tx() as c:
            row=c.execute('SELECT * FROM checkpoints WHERE job_id=? AND step=?',(job['id'],name)).fetchone()
            if row and row['state']=='succeeded':
                return json.loads(row['result'])
            if row and row['state'] in ('running','uncertain'):
                raise Uncertain('Prior external request requires reconciliation')
            if paid:
                validate=getattr(self.claude,'validate',None)
                if validate: validate()  # Local-only; before paid reservation/write intent.
                limit=self.config.integer('MAX_CLAUDE_CALLS_PER_DAY',12)
                start=dt.datetime.combine(dt.date.fromisoformat(kst_day()),dt.time(),ZoneInfo('Asia/Seoul')).astimezone(dt.timezone.utc).isoformat()
                count=c.execute("SELECT count(*) FROM checkpoints WHERE step LIKE 'claude%' AND created_at>=?",(start,)).fetchone()[0]
                if count>=limit:
                    raise Waiting('Daily Claude call cap reached (Asia/Seoul accounting)')
                token_limit=self.config.integer('MAX_RESERVED_TOKENS_PER_DAY',360000)
                # Reserve conservative input+output per call, including uncertain calls.
                if (count+1)*self.config.integer('TOKENS_RESERVED_PER_CALL',30000)>token_limit:
                    raise Waiting('Daily reserved token budget reached')
            c.execute('INSERT OR REPLACE INTO checkpoints(job_id,step,state,created_at) VALUES(?,?,?,?)',(job['id'],name,'running',now()))
            c.execute('UPDATE jobs SET stage=? WHERE id=?',(name,job['id']))
        try:
            result=call()
        except Exception as exc:
            with self.store.tx() as c:
                c.execute('UPDATE checkpoints SET state=? WHERE job_id=? AND step=?',('uncertain' if ambiguous else 'failed',job['id'],name))
            if ambiguous:
                raise Uncertain('External response uncertain; no automatic retry') from None
            raise exc
        with self.store.tx() as c:
            c.execute("UPDATE checkpoints SET state='succeeded',result=?,input_tokens=?,output_tokens=? WHERE job_id=? AND step=?",(json.dumps(result,ensure_ascii=False),result.get('input_tokens') if isinstance(result,dict) else None,result.get('output_tokens') if isinstance(result,dict) else None,job['id'],name))
        return result

    def run_one(self):
        if self.config.env.get('ENABLE_EXTERNAL_CALLS') != '1' or self.config.env.get('AUTOMATION_PAUSED') == '1':
            return False
        job=self.store.claim()
        if not job:
            return False
        p=json.loads(job['payload'])
        configuration_detail=''
        try:
            if job['kind']=='candidates': self.candidates(job,p)
            elif job['kind']=='draft': self.draft(job,p)
            elif job['kind']=='render': self.render(job,p)
            elif job['kind']=='publish': self.publish(job,p)
            elif job['kind']=='image_search': self.image_search(job,p)
            else: raise ValueError('Unknown job kind')
            state='succeeded'; error=None
        except ConfigurationError as exc:
            state='waiting';error=exc.code;configuration_detail=str(exc)
        except Waiting as exc:
            state='waiting'; error=exc.code
        except Uncertain:
            state='uncertain'; error='external_outcome_unknown'
        except Exception as exc:
            state='failed'; error=type(exc).__name__
        if job['kind']=='publish' and error:
            with self.store.tx() as c:
                c.execute("UPDATE publications SET state=?,updated_at=? WHERE selection_id=? AND state!='published'",(state,now(),p['id']))
        with self.store.tx() as c:
            c.execute('UPDATE jobs SET state=?,error_code=?,finished_at=? WHERE id=?',(state,error,now(),job['id']))
            self.store.event(c,job['id'],state,error or '')
            if error:
                self.store.notify(c,f'error:{job["id"]}:{job["attempts"]}',{'text':f'⚠️ 작업 {job["id"]} / {job["kind"]}: {state} ({error}). '+configuration_detail+' /status 로 확인하세요. 자동 유료 재호출 없음.'})
        return True

    def candidates(self, job, p):
        with self.store.tx() as c:
            batch=c.execute('SELECT * FROM batches WHERE id=?',(p['batch_id'],)).fetchone()
            if batch['day']!=kst_day():
                raise Waiting('Expired daily batch; do not catch up stale news')
        news=self.step(job,'rss',self.news)
        with self.store.tx() as c:
            prior=[json.loads(row[0]) for row in c.execute('SELECT x.payload FROM candidates x JOIN selections s ON s.candidate_id=x.id')]
        news=distinct_news(news,[{'url':x['source_url'],'title':x.get('source',{}).get('title',x['title'])} for x in prior])
        if len(news)<3:
            raise ValueError('Fewer than three fresh sources; no Claude request made')
        raw=self.step(job,'claude_candidates',lambda:self.claude.generate(candidate_prompt(news),3000),True,True)
        try:
            data=validate_candidates(parse_json(raw['raw']),news)
        except (ValueError,KeyError,TypeError):
            with self.store.tx() as c:c.execute("UPDATE batches SET status='review_required' WHERE id=?",(p['batch_id'],))
            raise Waiting('Candidate response requires review; saved response retained','candidate_response_invalid') from None
        with self.store.tx() as c:
            for i,candidate in enumerate(data['candidates'],1):
                c.execute('INSERT OR IGNORE INTO candidates(batch_id,position,title,payload,created_at) VALUES(?,?,?,?,?)',(p['batch_id'],i,candidate['title'],json.dumps(candidate,ensure_ascii=False),now()))
            c.execute("UPDATE batches SET status='ready' WHERE id=?",(p['batch_id'],))
            self.store.notify(c,f'candidates:{p["batch_id"]}',candidate_message(c,p['batch_id']))

    def draft(self, job, p):
        r=self.store.row(p['id'])
        if r['revision']!=p['revision'] or r['status'] not in ('selected','revision_requested','draft_ready'):
            raise ValueError('Draft no longer eligible')
        with self.store.tx() as c:
            candidate=c.execute('SELECT payload FROM candidates WHERE id=?',(r['candidate_id'],)).fetchone()
        if not candidate:
            raise Waiting('Legacy record: source must be imported explicitly; no fabricated evidence')
        source=json.loads(candidate[0])
        raw=self.step(job,'claude_draft',lambda:self.claude.generate(draft_prompt(source,r['revision_note'] or ''),4000),True,True)
        try:
            draft=validate_draft(parse_json(raw['raw']),source['source_url'])
        except (ValueError,KeyError,TypeError):
            with self.store.tx() as c:
                c.execute("UPDATE selections SET status='draft_invalid',draft_json=NULL WHERE id=? AND revision=?",(p['id'],p['revision']))
            raise Waiting('Draft response requires correction; saved response retained','draft_response_invalid') from None
        issues=draft_quality(draft)
        with self.store.tx() as c:
            c.execute('INSERT OR IGNORE INTO draft_versions VALUES(?,?,?,?)',(p['id'],p['revision'],json.dumps(draft,ensure_ascii=False),now()))
            changed=c.execute("UPDATE selections SET draft_json=?,status=? WHERE id=? AND revision=? AND status IN ('selected','revision_requested','draft_ready')",(json.dumps(draft,ensure_ascii=False),'draft_review' if issues else 'draft_ready',p['id'],p['revision'])).rowcount
            if changed!=1: raise ValueError('Content changed')
            if issues:
                c.execute('INSERT OR REPLACE INTO quality_reviews VALUES(?,?,?,NULL)',(p['id'],p['revision'],json.dumps(issues)))
                self.store.notify(c,f'quality:{p["id"]}:{p["revision"]}',{'text':f'원고 품질 검토 필요: {p["id"]} v{p["revision"]}: '+', '.join(issues)+f'\n/preview {p["id"]}\n/revise {p["id"]} 수정내용 또는 검토 후 /acceptdraft {p["id"]} {p["revision"]}'})
            else:
                self.store.enqueue(c,f'render:{p["id"]}:{p["revision"]}','render',p)
            self.store.notify(c,f'draft:{p["id"]}:{p["revision"]}',{'text':f'📝 원고 {p["id"]} v{p["revision"]}\n'+draft['caption']+'\n\n'+'\n\n'.join(s.get('headline','')+'\n'+s.get('body','') for s in draft['slides'][:3])})
        if issues: raise Waiting('Editorial review required','draft_quality_review')

    def render(self, job, p):
        r=self.store.row(p['id'])
        if r['revision']!=p['revision'] or r['status'] not in ('draft_ready','preview_ready'):
            raise ValueError('Render version changed')
        draft=json.loads(r['draft_json'])
        with self.store.tx() as c:
            image=c.execute('SELECT payload FROM image_inputs WHERE selection_id=? AND revision=?',(p['id'],p['revision'])).fetchone()
        provenance={'source':'approved_figma_backgrounds','manual_review_required':True}
        if image or self.config.env.get('REQUIRE_TOPIC_IMAGE','1')=='1':
            from .images import select_photos, SLOTS
            existing=json.loads(image[0]) if image else {}
            # Legacy single-photo input covers only the content frame.
            existing=existing.get('photos',{}) if 'photos' in existing else ({'content':existing} if existing else {})
            with self.store.tx() as c:
                library=c.execute('SELECT * FROM image_library').fetchall()
            try:
                chosen=select_photos(library,draft.get('image_queries',{}),existing)
            except (ValueError,OSError):
                with self.store.tx() as c:
                    self.store.notify(c,f'image-invalid:{p["id"]}:{p["revision"]}',{'text':f'사진 재검토 필요: {p["id"]} v{p["revision"]}. 등록 파일·해시·해상도·검토 이력·사진 중복을 확인하세요.'})
                raise Waiting('Photographic inputs need manual reinspection') from None
            with self.store.tx() as c:
                if chosen:
                    c.execute('INSERT OR REPLACE INTO image_inputs VALUES(?,?,?,?)',(p['id'],p['revision'],json.dumps({'photos':chosen}),now()))
                if set(chosen)!=set(SLOTS):
                    self.store.notify(c,f'image-review:{p["id"]}:{p["revision"]}',{'text':f'사진 수동 검토 필요: {p["id"]} v{p["revision"]}. 본문/중간 결의에 서로 다른 고해상도 실사 2장을 등록하세요. 저해상도·AI·명확한 얼굴 사진은 사용하지 않습니다.'})
                    if self.config.env.get('AUTO_IMAGE_SEARCH')=='1':
                        for slot in SLOTS:
                            query=draft.get('image_queries',{}).get(slot)
                            if slot not in chosen and query:
                                self.store.enqueue(c,f'image-search:{p["id"]}:{p["revision"]}:{slot}','image_search',dict(p,slot=slot,query=query))
            if set(chosen)!=set(SLOTS):
                raise Waiting('Two distinct reviewed topic photographs required')
            draft['slides'][1]['background_image']=chosen['content']['path']
            draft['slides'][2]['background_image']=chosen['resolution_extra']['path']
            provenance={'photos':chosen}
        media=self.step(job,'render',lambda:self.media.render(draft,p['id'],p['revision']))
        media['image_provenance']=provenance
        # Persist artifacts before network validation/delivery.
        with self.store.tx() as c:
            c.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?,?)',(p['id'],p['revision'],json.dumps(media),now()))
        if self.config.env.get('RENDER_DIR'):
            if self.config.env.get('ENABLE_PUBLIC_MEDIA')=='1':
                self.step(job,'expose_public',lambda:self.media.expose(media))
                self.step(job,'verify_public',lambda:self.media.verify(media))
        else:
            self.step(job,'verify_public',lambda:self.media.verify(media))
        with self.store.tx() as c:
            changed=c.execute("UPDATE selections SET status='preview_ready',image_paths=? WHERE id=? AND revision=? AND status IN ('draft_ready','preview_ready')",(json.dumps(media['urls']),p['id'],p['revision'])).rowcount
            if changed!=1: raise ValueError('Preview version changed')
            self.store.notify(c,f'media:{p["id"]}:{p["revision"]}',{'text':f'카드뉴스 {p["id"]} v{p["revision"]} / {len(media["files"])}장','files':media['files'],'sha256':media['sha256']})
            approval=preview_message(p['id'],p['revision'])
            approval['after_delivery']=f'media:{p["id"]}:{p["revision"]}'
            self.store.notify(c,f'approval:{p["id"]}:{p["revision"]}',approval)

    def image_search(self, job, p):
        from .images import pixabay_search
        if 'revision' in p:
            current=self.store.row(p['id'])
            if current['revision']!=p['revision'] or current['status']!='draft_ready':
                raise Waiting('Photo search version changed')
        result=self.step(job,'pixabay_search',lambda:pixabay_search(self.config,p['query']))
        lines=[f'사진 검색: 게시물 {p["id"]}. 자동 얼굴 검출/라이선스 승인이 아닙니다.']
        for item in result[:5]:
            lines.append(f'Pixabay ID {item["id"]}: {item["source_url"]}')
        lines.append('관리자가 사진을 확인한 뒤 download-image → attach-image로 원본 해상도·권리·관련성·얼굴 검토를 등록하세요. 미충족 시 다른 합법적 소스의 수동 사진을 등록하세요.')
        with self.store.tx() as c:
            self.store.notify(c,f'images:{job["id"]}',{'text':'\n'.join(lines)})
        if not result: raise Waiting('No suitable image candidates; manual review required')

    def publish(self, job, p):
        r=self.store.row(p['id'])
        if r['revision']!=p['revision'] or r['approved_revision']!=p['revision'] or r['reviewed_revision']!=p['revision'] or r['status'] not in ('approved','publish_waiting','published'):
            raise Waiting('Explicit review and approval of this exact revision required')
        if r['published_id']:
            return
        with self.store.tx() as c:
            c.execute("INSERT OR IGNORE INTO publications(selection_id,revision,state,updated_at) VALUES(?,?,'pending',?)",(p['id'],p['revision'],now()))
        if not self.instagram.enabled():
            with self.store.tx() as c:
                c.execute("UPDATE selections SET status='publish_waiting' WHERE id=?",(p['id'],))
            raise Waiting('Instagram publishing disabled or unconfigured')
        if self.config.env.get('RENDER_DIR') and self.config.env.get('ENABLE_PUBLIC_MEDIA')!='1':
            raise Waiting('Separate permission to expose public media required','public_media_disabled')
        with self.store.tx() as c:
            a=c.execute('SELECT payload FROM assets WHERE selection_id=? AND revision=?',(p['id'],p['revision'])).fetchone()
        if not a: raise Waiting('Approved assets missing')
        media=json.loads(a[0]); draft=json.loads(r['draft_json'])
        if self.config.env.get('RENDER_DIR'):
            self.step(job,'expose_public',lambda:self.media.expose(media))
        self.step(job,'publish_verify_public',lambda:self.media.verify(media))
        self.instagram.preflight()  # Refresh token/permissions/quota on every explicit resume
        with self.store.tx() as c:
            c.execute("INSERT OR IGNORE INTO publications(selection_id,revision,state,updated_at) VALUES(?,?,'preparing',?)",(p['id'],p['revision'],now()))
        children=[]
        for i,url in enumerate(media['urls']):
            child=self.step(job,f'ig_child_{i}',lambda url=url:self.instagram.child(url),True)
            children.append(child['id'])
            with self.store.tx() as c:
                c.execute('UPDATE publications SET children=?,updated_at=? WHERE selection_id=?',(json.dumps(children),now(),p['id']))
            self.step(job,f'ig_child_ready_{i}',lambda child=child:self.instagram.ready(child['id']))
        container=self.step(job,'ig_container',lambda:self.instagram.carousel(children,draft['caption']),True)
        with self.store.tx() as c:
            c.execute("UPDATE publications SET container_id=?,state='container_ready',updated_at=? WHERE selection_id=?",(container['id'],now(),p['id']))
        self.step(job,'ig_ready',lambda:self.instagram.ready(container['id']))
        with self.store.tx() as c:
            c.execute("UPDATE publications SET state='publishing',updated_at=? WHERE selection_id=?",(now(),p['id']))
        # Persist the write intent BEFORE publishing. A timeout is never auto-retried.
        result=self.step(job,'ig_publish',lambda:self.instagram.publish(container['id']),True)
        with self.store.tx() as c:
            c.execute("UPDATE publications SET state='published',media_id=?,updated_at=? WHERE selection_id=?",(result['id'],now(),p['id']))
            c.execute("UPDATE selections SET status='published',published_id=? WHERE id=?",(result['id'],p['id']))
            self.store.notify(c,f'published:{p["id"]}',{'text':f'✅ 게시 완료: {p["id"]} / Instagram ID {result["id"]}'})

    def deliver_one(self):
        if self.config.env.get('ENABLE_EXTERNAL_CALLS') != '1' or self.config.env.get('AUTOMATION_PAUSED') == '1':
            return False
        # A committed 'sending' is durable: process death never causes blind replay.
        with self.store.tx() as c:
            if c.execute("SELECT 1 FROM outbox WHERE state='sending'").fetchone(): return False
            r=c.execute("""SELECT * FROM outbox o WHERE state='queued' AND
                (json_extract(o.payload,'$.after_delivery') IS NULL OR EXISTS(
                    SELECT 1 FROM outbox dependency WHERE dependency.delivery_key=json_extract(o.payload,'$.after_delivery') AND dependency.state='sent'))
                ORDER BY id LIMIT 1""").fetchone()
            if not r: return False
            c.execute("UPDATE outbox SET state='sending' WHERE id=?",(r['id'],))
        try:
            ids=self.telegram.send(json.loads(r['payload'])); state='sent'; error=None
        except Exception:
            ids=None; state='uncertain'; error='delivery_outcome_unknown'
        with self.store.tx() as c:
            c.execute('UPDATE outbox SET state=?,remote_ids=?,error_code=? WHERE id=?',(state,json.dumps(ids),error,r['id']))
        return True


def candidate_message(c,batch):
    rows=c.execute('SELECT * FROM candidates WHERE batch_id=? ORDER BY position',(batch,)).fetchall()
    lines=['🏛️ 오늘의 뉴스 기반 가상 심의 후보 (출처 원문 확인 필요)']; buttons=[]
    for row in rows:
        p=json.loads(row['payload'])
        lines.append(f'{row["position"]}. {row["title"]}\n{p["summary"]}\n풍자 방향: {p["satire_angle"]}\n출처: '+p.get('source',{}).get('publisher','원문 버튼 확인'))
        row_buttons=[]
        if row['status']=='available': row_buttons.append({'text':f'{row["position"]}번 선택','callback_data':f'candidate:{row["id"]}'})
        row_buttons.append({'text':f'{row["position"]}번 원문','url':p['source_url']})
        buttons.append(row_buttons)
    buttons.append([{'text':'후보 묶음 거절','callback_data':f'batchreject:{batch}'}])
    return {'text':'\n\n'.join(lines),'reply_markup':{'inline_keyboard':buttons}}


def preview_message(rid,revision):
    return {'text':f'심의 {rid} v{revision}\n원문·사실/창작 구분·한국어 문장·이미지 관련성·라이선스·얼굴/초상권을 직접 검토하세요.\n/review {rid} {revision} 로 검토 확인 후 승인하세요.\n수정: /revise {rid} 수정 요청\n원고/이미지 재조회: /preview {rid}',
            'reply_markup':{'inline_keyboard':[[{'text':'게시 승인','callback_data':f'approve:{rid}:{revision}'},{'text':'거절','callback_data':f'reject:{rid}:{revision}'}],[{'text':'원고 재생성','callback_data':f'regenerate:{rid}:{revision}'}]]}}
