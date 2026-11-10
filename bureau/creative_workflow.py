"""Durable staged creation. Human planning/final approvals remain separate gates."""
import json
from . import creative as c2
from .store import now, kst_day
from .content import parse_json


class InvalidCreativeOutput(ValueError):
    pass


class CreativeWorkflow:
    def __init__(self,engine):self.e=engine;self.store=engine.store;self.config=engine.config

    def artifact(self,rid,revision,stage,iteration,data):
        with self.store.tx() as c:
            c.execute('INSERT OR REPLACE INTO creative_artifacts VALUES(?,?,?,?,?,?)',(rid,revision,stage,iteration,json.dumps(data,ensure_ascii=False),now()))

    def call(self,job,stage,data,iteration=0,maximum=4000):
        from .engine import Waiting
        request=c2.request(stage,data);model=c2.model_for(self.config,stage)
        step=f'claude_v2_{stage}_{iteration}'
        request_hash=c2.fingerprint(dict(request,model=model,max_tokens=maximum))
        with self.store.tx() as c:
            prior=c.execute('SELECT request_sha256 FROM creative_calls WHERE job_id=? AND step=?',(job['id'],step)).fetchone()
            if prior and prior[0]!=request_hash:raise Waiting('Saved creative request changed; create an explicitly requested revision','creative_request_changed')
            c.execute('INSERT OR IGNORE INTO creative_calls(job_id,step,stage,model_id,prompt_version,request_sha256,request_json,state,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                (job['id'],step,stage,model,request['prompt_version'],request_hash,c2.canonical(dict(request,model=model,max_tokens=maximum)),'planned',now()))
        def generate():
            return self.e.claude.generate_role(stage,request['system'],request['user'],maximum,model=model)
        try:
            result=self.e.step(job,step,generate,True,True)
        finally:
            with self.store.tx() as c:
                state=c.execute('SELECT state FROM checkpoints WHERE job_id=? AND step=?',(job['id'],step)).fetchone()
                c.execute('UPDATE creative_calls SET state=? WHERE job_id=? AND step=?',(state[0] if state else 'blocked',job['id'],step))
        estimated=None
        role=stage.upper()
        inp=self.config.env.get(f'CLAUDE_{role}_INPUT_PER_MTOK_USD')
        out=self.config.env.get(f'CLAUDE_{role}_OUTPUT_PER_MTOK_USD')
        if inp and out:
            from decimal import Decimal
            rates=[Decimal(inp),Decimal(out)]
            if any(not x.is_finite() or x<0 for x in rates):raise ValueError('Invalid configured model rate')
            estimated=float((Decimal(result.get('input_tokens',0))*rates[0]+Decimal(result.get('output_tokens',0))*rates[1])/Decimal(1_000_000))
        with self.store.tx() as c:
            c.execute('UPDATE creative_calls SET input_tokens=?,output_tokens=?,estimated_usd=? WHERE job_id=? AND step=?',(result.get('input_tokens'),result.get('output_tokens'),estimated,job['id'],step))
        try:
            data=parse_json(result['raw'])
            if not isinstance(data,dict):raise ValueError('Object required')
            return data
        except (ValueError,TypeError,KeyError):
            raise InvalidCreativeOutput('저장된 모델 응답이 JSON 객체 형식을 충족하지 못했습니다.') from None

    def context(self):
        with self.store.tx() as c:
            topics=[json.loads(r[0]) for r in c.execute('SELECT payload FROM candidates ORDER BY id DESC LIMIT 120')]
            history=[dict(r) for r in c.execute('SELECT * FROM creative_history ORDER BY created_at DESC LIMIT 30')]
            legacy=[]
            for row in c.execute('SELECT id,draft_json FROM selections WHERE draft_json IS NOT NULL ORDER BY id DESC LIMIT 12'):
                old=json.loads(row['draft_json'])
                if old.get('schema_version')!=2:
                    narrative=old.get('slides',[])
                    legacy.append({'source':'legacy manuscript; type unclassified','format':'legacy_hearing','verdict_type':'unclassified_legacy','domain':'unknown','anchor':str(narrative[2].get('body',''))[-150:] if len(narrative)>2 else ''})
            feedback=[{'reference':r['source_ref'],'text':r['feedback'],'original_ruling':json.loads(r['draft_json'])['slides'][-2]['body']} for r in c.execute('SELECT a.*,s.draft_json FROM creative_appeals a JOIN selections s ON s.id=a.parent_selection_id WHERE s.published_id IS NOT NULL ORDER BY a.id DESC LIMIT 6')]
        return {'topics':[x.get('creative_brief',x) for x in topics],'history':history,'legacy_history':legacy[:3],'source_feedback':feedback}

    def candidates(self,job,p):
        from .engine import Waiting,candidate_message
        context=self.context()
        with self.store.tx() as c:
            batch=c.execute('SELECT * FROM batches WHERE id=?',(p['batch_id'],)).fetchone()
            if not batch or batch['day']!=kst_day():raise Waiting('Expired candidate batch')
            if not p.get('rejected_id') and batch['status']=='ready':return
            if p.get('rejected_id'):
                row=c.execute('SELECT position FROM candidates WHERE id=?',(p['rejected_id'],)).fetchone()
                if row and row[0]<0:return
        prompt_context=dict(context,topics=[{k:x.get(k,'')[:100] for k in ('title','objective','summary','domain','conflict_key','comic_anchor')} for x in context['topics'][:12]])
        data=self.call(job,'ideas',dict(prompt_context,domains=c2.DOMAINS),maximum=7000)
        items=data.get('candidates',[])
        if len(items)<12 or len({x.get('domain') for x in items})<6:raise Waiting('Candidate pool needs 12 concrete scenes across six domains','creative_candidates_insufficient')
        needed=1 if p.get('rejected_id') else 3
        try:chosen=c2.choose_candidates(items,context['topics'],needed)
        except ValueError:raise Waiting('Distinct grounded candidates unavailable; human editorial review needed','creative_candidates_rejected') from None
        with self.store.tx() as c:
            for item in items:
                c.execute('INSERT INTO idea_audits(subject,payload,accepted,checks,created_at) VALUES(?,?,?,?,?)',(str(job['id']),c2.canonical(item),int(item in chosen),c2.canonical({'method':'grounding/domain/history; no humor success claim'}),now()))
            if p.get('rejected_id'):c.execute('UPDATE candidates SET position=-id WHERE id=?',(p['rejected_id'],))
            for i,item in enumerate(chosen,p.get('position',1)):
                payload=dict(creative_version=2,creative_brief=item,title=item['title'],summary=item['objective'],empathy=item['empathy'],hook=item['hook'],satire_angle='판정 미정 · '+item['issue'],share_reason=item['share_reason'],situation_key=item['conflict_key'],source_url=None)
                c.execute('INSERT OR IGNORE INTO candidates(batch_id,position,title,payload,created_at) VALUES(?,?,?,?,?)',(p['batch_id'],i,item['title'],c2.canonical(payload),now()))
            c.execute("UPDATE batches SET status='ready' WHERE id=?",(p['batch_id'],))
            message=candidate_message(c,p['batch_id'],p.get('position') if p.get('rejected_id') else None)
            # Same scheduling expiry as the legacy candidate delivery.
            origin=c.execute("SELECT detail FROM events WHERE subject=? AND action='scheduled' ORDER BY id LIMIT 1",(str(p['batch_id']),)).fetchone()
            if origin and json.loads(origin[0])['source']=='vm_timer':
                import datetime as dt
                from zoneinfo import ZoneInfo
                message['expires_at']=dt.datetime.combine(dt.date.fromisoformat(batch['day']),dt.time(18,5),ZoneInfo('Asia/Seoul')).astimezone(dt.timezone.utc).isoformat()
            self.store.notify(c,f'creative-candidates:{job["id"]}',message)

    def draft(self,job,p):
        from .engine import Waiting,plan_message
        r=self.store.row(p['id']);rid=p['id'];revision=p['revision']
        if r['revision']!=revision or r['status'] not in ('selected','revision_requested','draft_ready'):raise ValueError('Draft version changed')
        with self.store.tx() as c:
            row=c.execute('SELECT payload FROM candidates WHERE id=?',(r['candidate_id'],)).fetchone()
        source=json.loads(row[0]) if row else {}
        if source.get('creative_version')!=2:
            self.hold(rid,revision,{'reason':'기존 소재는 A/B 행동·주장을 확인한 v2 brief로 새로 선택해야 합니다.'})
            return
        candidate=source['creative_brief'];c2.validate_candidate(candidate)
        context=self.context()
        context['history']=[h for h in context['history'] if h['selection_id']!=rid]
        with self.store.tx() as c:
            previous=c.execute('SELECT payload FROM draft_versions WHERE selection_id=? AND revision<? ORDER BY revision DESC LIMIT 1',(rid,revision)).fetchone()
        if not previous:
            with self.store.tx() as c:
                previous=c.execute("SELECT payload FROM creative_artifacts WHERE selection_id=? AND revision<? AND stage='draft' ORDER BY revision DESC,iteration DESC LIMIT 1",(rid,revision)).fetchone()
        prior_draft=json.loads(previous[0]) if previous else None
        context['source_feedback']=[x for x in context['source_feedback'] if x['reference']==candidate.get('appeal_reference')]
        model_history=[{k:h[k] for k in ('domain','format','verdict_type','anchor')} for h in context['history'][:6]]+context['legacy_history']
        # Do not feed the current idea back as a duplicate of itself.
        plan=self.call(job,'conflict',dict(candidate=candidate,formats=c2.FORMATS,history=model_history,source_feedback=context['source_feedback'],editor_note=r['revision_note'] or ''))
        c2.validate_conflict(plan,candidate,context['source_feedback']);self.artifact(rid,revision,'conflict',0,plan)
        verdicts=self.call(job,'verdict',dict(plan=plan,verdict_types=c2.VERDICT_TYPES,criteria=c2.CRITERIA,history=model_history))
        options=c2.validate_verdicts(verdicts,plan)
        try:selected=c2.select_verdict(options,context['history'],plan['format'])
        except ValueError:
            self.artifact(rid,revision,'verdict',0,verdicts)
            self.hold(rid,revision,{'reason':'소재 적합성·의외성·유머 기준 또는 최근 판정 반복 검사를 통과하지 못했습니다. 낮은 품질의 다른 유형으로 대체하지 않고 새 판정 설계를 요청합니다.'})
            return
        self.artifact(rid,revision,'verdict',0,verdicts)
        feedback=None;draft=None;review=None
        for iteration in range(3):
            data=dict(plan=plan,facts_hash=c2.fingerprint(plan['facts']),formats=c2.FORMATS,verdict_options=options,selected_verdict=selected,editor_note=r['revision_note'] or '',previous_draft=draft or prior_draft,editor_feedback=feedback)
            try:candidate_draft=self.call(job,'draft',data,iteration)
            except InvalidCreativeOutput as exc:
                feedback={'validation_error':str(exc)}
                self.artifact(rid,revision,'validation',iteration,feedback)
                continue
            try:c2.ground_draft(candidate_draft,plan,options)
            except ValueError as exc:
                feedback={'validation_error':str(exc),'instruction':'Change the scene treatment or ruling, preserve frozen facts; no score chasing.'}
                self.artifact(rid,revision,'validation',iteration,feedback)
                draft=candidate_draft
                continue
            draft=candidate_draft;self.artifact(rid,revision,'draft',iteration,draft)
            try:review=self.call(job,'editor',dict(draft=draft,plan=plan,verdict_options=[{k:v for k,v in option.items() if k not in ('fit','surprise','humor')} for option in options],history=model_history),iteration,maximum=2400)
            except InvalidCreativeOutput as exc:
                feedback={'validation_error':str(exc)}
                self.artifact(rid,revision,'validation',iteration,feedback)
                continue
            self.artifact(rid,revision,'editor',iteration,review)
            try:accepted=c2.review_accepted(review,draft)
            except ValueError as exc:
                accepted=False;review=dict(review,validation_error=str(exc))
                self.artifact(rid,revision,'editor',iteration,review)
            if accepted:
                draft=dict(draft,editorial_checkpoint={'revision':revision,'iteration':iteration,'draft_hash':c2.fingerprint(c2.editorial_text(draft))},test_only=bool(candidate.get('test_only') or source.get('test_only') or draft.get('test_only')),publication_kind='official',creative_version=c2.VERSION,editorial_accepted=True,
                    case_number='가상 사건 '+str(rid)+'-'+str(revision),creative_provenance={'domain':candidate['domain'],'conflict_key':candidate['conflict_key'],'verdict_type':next(v['type'] for v in options if v['id']==draft['verdict_id']),'anchor':candidate['comic_anchor'],'source_feedback':context['source_feedback'] if plan['format']=='appeal' else []})
                with self.store.tx() as c:
                    changed=c.execute("UPDATE selections SET draft_json=?,status='planning_review',approved_revision=NULL,reviewed_revision=NULL WHERE id=? AND revision=? AND status IN ('selected','revision_requested','draft_ready')",(c2.canonical(draft),rid,revision)).rowcount
                    if changed!=1:raise ValueError('Draft changed during editorial review')
                    c.execute('INSERT OR REPLACE INTO draft_versions VALUES(?,?,?,?)',(rid,revision,c2.canonical(draft),now()))
                    cp=draft['creative_provenance']
                    c.execute('INSERT OR REPLACE INTO creative_history VALUES(?,?,?,?,?,?,?,?)',(rid,revision,cp['domain'],cp['conflict_key'],draft['format'],cp['verdict_type'],cp['anchor'],now()))
                    message=plan_message(rid,revision,draft)
                    message['text']+='\n\n편집장 검토: '+str(sum(review['scores'].values()))+'/50 (모델 평가이며 재미 보증 아님)\n가장 약한 문장: '+review['boring_sentence']+'\n마지막 장 개선 의견: '+review['ending_improvement']
                    message['reply_markup']['inline_keyboard'].append([{'text':'편집장 의견 전체','callback_data':f'editorreport:{rid}:{revision}'}])
                    self.store.notify(c,f'creative-plan:{rid}:{revision}',message)
                return
            feedback=review
        self.hold(rid,revision,feedback or review or {'reason':'원고 검증 미통과'})

    def hold(self,rid,revision,report):
        with self.store.tx() as c:
            changed=c.execute("UPDATE selections SET status='editorial_hold',approved_revision=NULL,reviewed_revision=NULL WHERE id=? AND revision=? AND status IN ('selected','revision_requested','draft_ready')",(rid,revision)).rowcount
            if changed!=1:raise ValueError('Stale editorial hold')
            self.store.notify(c,f'creative-hold:{rid}:{revision}',{'text':f'게시 보류 · {rid} v{revision}\n기준을 충족하지 못해 게시하지 않습니다. 원고 재작성은 최대 2회까지만 허용하며 점수만 올려 통과시키지 않습니다.\n'+c2.editor_report_text(report)[:2800],
                'reply_markup':{'inline_keyboard':[[{'text':'편집 방향을 지정해 새 버전 요청','callback_data':f'creativeedit:{rid}:{revision}'}],[{'text':'편집장 의견','callback_data':f'editorreport:{rid}:{revision}'}]]}})

    def image_brief(self,job,p,draft):
        if draft.get('test_only'):raise ValueError('Test fixtures cannot invoke production image preparation')
        if not draft.get('editorial_accepted'):raise ValueError('Images cannot precede editorial acceptance')
        queries=self.call(job,'image_brief',{'draft':draft},maximum=700).get('image_queries',{})
        if set(queries)!={'content','resolution_extra'} or any(not isinstance(v,str) or not 3<=len(v)<=80 for v in queries.values()):raise ValueError('Two bounded image queries required')
        draft=dict(draft,image_queries=queries)
        with self.store.tx() as c:
            row=c.execute('SELECT revision,status FROM selections WHERE id=?',(p['id'],)).fetchone()
            if row['revision']!=p['revision'] or row['status']!='draft_ready':raise ValueError('Planning approval changed')
            c.execute('UPDATE selections SET draft_json=? WHERE id=?',(c2.canonical(draft),p['id']))
            c.execute('UPDATE draft_versions SET payload=? WHERE selection_id=? AND revision=?',(c2.canonical(draft),p['id'],p['revision']))
        return draft
