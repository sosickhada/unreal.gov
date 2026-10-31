import json
from .config import Config
from .store import Store, kst_day, now
from .engine import candidate_message, preview_message, plan_message


def build_app(config):
    from telegram import InlineKeyboardMarkup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
    config.require_external()
    e=config.env; store=Store(config.db)
    from .preflight import telegram_settings
    telegram_settings(e)
    allowed={uid.strip() for uid in e['TELEGRAM_ALLOWED_USER_IDS'].split(',') if uid.strip()}

    def authorized(update):
        return bool(update.effective_chat and update.effective_user and str(update.effective_chat.id)==e['TELEGRAM_CHAT_ID'] and str(update.effective_user.id) in allowed)

    def queue(update,payload,suffix='reply'):
        with store.tx() as c:
            store.notify(c,f'update:{update.update_id}:{suffix}',payload)

    async def command(update,context):
        if update.message.text.split()[0].split('@')[0]=='/whoami':
            # Same listener; no second getUpdates consumer. Private chat only.
            if update.effective_chat and update.effective_user and update.effective_chat.type=='private' and str(update.effective_chat.id)==e['TELEGRAM_CHAT_ID']:
                await update.message.reply_text('본인 Telegram 사용자 ID: '+str(update.effective_user.id))
            return
        if not authorized(update): return
        name=update.message.text.split()[0].split('@')[0][1:]
        try:
            if name=='start':
                payload={'text':'🏛️ 비현실문제부\n/candidates /preview ID /status\n/revise ID 수정내용 /review ID VERSION\n/newcandidates (유료 후보 재생성 요청)\n/retry JOB_ID /resend DELIVERY_ID CONFIRM\n승인은 검토한 버전에만 적용됩니다.'}
            elif name=='candidates':
                with store.tx() as c:
                    b=c.execute("SELECT id FROM batches WHERE day=? AND status='ready' ORDER BY generation DESC LIMIT 1",(kst_day(),)).fetchone()
                    payload=candidate_message(c,b[0]) if b else {'text':'오늘 저장된 후보가 없습니다. 예약 작업 또는 관리자 상태를 확인하세요.'}
            elif name=='newcandidates':
                job=store.schedule(regenerate=True,maximum=config.integer('MAX_CANDIDATE_REGENERATIONS',2),request_key=f'newcandidates:{update.update_id}',source='telegram')
                payload={'text':f'새 후보 생성 요청 접수: 작업 {job}. 일일 호출 상한이 적용됩니다.'}
            elif name=='photos':
                from .photo_review import offer
                rid=int(context.args[0]);r=store.row(rid)
                count=offer(store,rid,r['revision'])
                payload={'text':f'사진 후보 {count}개를 보냈습니다. 적합한 사진만 검토 완료 버튼으로 선택하세요.'}
            elif name=='images':
                rid=int(context.args[0]); query=' '.join(context.args[1:]); store.row(rid)
                if not query or len(query)>100: raise ValueError('Use /images ID concrete English subject/action')
                with store.tx() as c:
                    jid=store.enqueue(c,f'images:{update.update_id}','image_search',{'id':rid,'query':query})
                payload={'text':f'사진 검색 접수: 작업 {jid}. 결과는 수동 검토가 필요합니다.'}
            elif name=='status':
                with store.tx() as c:
                    jobs=[dict(r) for r in c.execute('SELECT id,kind,state,stage,error_code FROM jobs ORDER BY id DESC LIMIT 12')]
                    records=[dict(r) for r in c.execute('SELECT id,status,revision FROM selections ORDER BY id DESC LIMIT 8')]
                    deliveries=[dict(r) for r in c.execute("SELECT id,state FROM outbox WHERE state IN ('uncertain','sending') ORDER BY id DESC LIMIT 8")]
                    publications=[dict(r) for r in c.execute('SELECT selection_id,revision,state FROM publications ORDER BY updated_at DESC LIMIT 8')]
                payload={'text':json.dumps({'jobs':jobs,'contents':records,'publications':publications,'deliveries_requiring_inspection':deliveries},ensure_ascii=False,indent=2)}
            elif name=='preview':
                rid=int(context.args[0]); r=store.row(rid)
                version=int(context.args[1]) if len(context.args)>1 else r['revision']
                if version!=r['revision']:
                    with store.tx() as c:
                        saved=c.execute('SELECT payload FROM draft_versions WHERE selection_id=? AND revision=?',(rid,version)).fetchone()
                    if not saved: raise ValueError('Unknown draft version')
                    r=dict(r,draft_json=saved[0])
                if r['draft_json']:
                    d=json.loads(r['draft_json'])
                    queue(update,{'text':f'원고 {rid} v{version}\n'+d.get('caption','')+'\n\n'+'\n\n'.join(s.get('headline','')+'\n'+s.get('body','') for s in d['slides'][:3])},'draft')
                with store.tx() as c:
                    a=c.execute('SELECT payload FROM assets WHERE selection_id=? AND revision=?',(rid,version)).fetchone()
                if a:
                    media=json.loads(a[0]); queue(update,{'text':f'미리보기 {rid} v{version}','files':media['files'],'sha256':media['sha256']},'images')
                payload=plan_message(rid,r['revision'],json.loads(r['draft_json'])) if r['status'] in ('planning_review','draft_review') and version==r['revision'] else preview_message(rid,r['revision']) if r['status']=='preview_ready' and version==r['revision'] else {'text':f'게시물 {rid}: {r["status"]}. 기존 승인 기록은 유지됩니다.'}
                if a and r['status']=='preview_ready' and version==r['revision']:
                    payload['after_delivery']=f'update:{update.update_id}:images'
            elif name=='revise':
                rid=int(context.args[0]); note=' '.join(context.args[1:])
                rev=store.revise(rid,note,config.integer('MAX_CONTENT_REVISIONS',3),request_key=f'revise:{update.update_id}'); payload={'text':f'원고 수정 접수: {rid} v{rev}'}
            elif name=='review':
                rid,rev=map(int,context.args); store.review(rid,rev)
                payload={'text':f'{rid} v{rev}: 출처·사실/창작 구분·문장·얼굴/초상권·이미지 관련성·라이선스·디자인 검토를 확인했습니다. 게시 승인 버튼으로 별도 승인하세요.'}
            elif name=='acceptdraft':
                rid,rev=map(int,context.args);store.accept_draft(rid,rev)
                payload={'text':f'{rid} v{rev} 원고 품질 검토를 기록했습니다. 렌더링 후 최종 이미지 검토·승인은 별도입니다.'}
            elif name=='retry':
                from .cli import resume
                resume(store,int(context.args[0])); payload={'text':'저장된 체크포인트부터 작업을 재개합니다. 불확실한 외부 쓰기는 재시도하지 않습니다.'}
            elif name=='resend':
                if len(context.args)!=2 or context.args[1]!='CONFIRM': raise ValueError('Use /resend DELIVERY_ID CONFIRM after checking for duplicate messages')
                with store.tx() as c:
                    if c.execute('SELECT 1 FROM requests WHERE request_key=?',(f'resend:{update.update_id}',)).fetchone(): return
                    c.execute('INSERT INTO requests VALUES(?,?)',(f'resend:{update.update_id}','accepted'))
                    changed=c.execute("UPDATE outbox SET state='queued',error_code=NULL WHERE id=? AND state='uncertain'",(int(context.args[0]),)).rowcount
                    if changed!=1: raise ValueError('Only uncertain deliveries may be replayed')
                    store.event(c,context.args[0],'operator_resend','possible duplicate acknowledged')
                payload={'text':'저장된 메시지 재전송을 요청했습니다. Claude는 호출하지 않습니다.'}
            else: return
            queue(update,payload)
        except (ValueError,IndexError,TypeError) as exc:
            queue(update,{'text':'현재 단계·버전·명령 인수를 확인하세요. 요청을 처리하지 못했습니다.'})

    async def callback(update,context):
        query=update.callback_query
        if not authorized(update):
            if query: await query.answer('접근 권한 없음')
            return
        try:
            parts=query.data.split(':'); action=parts[0]
            if action=='photopick':
                from .photo_review import approve
                ready=approve(store,int(parts[1]),int(parts[2]),int(parts[3]),parts[4],str(update.effective_user.id))
                text='사진 검토 기록을 저장했습니다. '+('두 사진이 준비되어 렌더링을 재개합니다.' if ready else '다른 슬롯의 사진도 검토·선택하세요.')
            elif action=='candidate':
                rid=store.select(int(parts[1])); text=f'후보 선택 접수: {rid}. 기획안을 생성한 뒤 승인 버튼을 보내드립니다. /preview {rid}'
            elif action=='batchregen':
                # Batch-bound request key makes concurrent/replayed clicks idempotent.
                with store.tx() as c:
                    batch=c.execute("SELECT id FROM batches WHERE id=? AND day=? AND status='ready'",(int(parts[1]),kst_day())).fetchone()
                    if not batch: raise ValueError('후보가 만료되었거나 준비 중입니다.')
                jid=store.schedule(regenerate=True,maximum=config.integer('MAX_CANDIDATE_REGENERATIONS',2),request_key=f'batchregen:{parts[1]}',source='telegram')
                text=f'후보 다시 생성 접수: 작업 {jid}'
            elif action=='planapprove':
                store.accept_draft(int(parts[1]),int(parts[2])); text='기획 승인 완료. 이미지 렌더링을 접수했습니다.'
            elif action in ('planedit','imageedit'):
                store.await_revision(str(update.effective_user.id),int(parts[1]),int(parts[2]),'image' if action=='imageedit' else 'plan')
                text='수정할 내용을 자연어로 보내주세요 (1–1000자). 이미지 수정은 사진 소재 요청이며 자동 검색·검증 후 새 이미지를 준비합니다. /cancelrevision 으로 입력을 취소합니다.'
            elif action=='back':
                batch=store.return_candidates(int(parts[1]),int(parts[2]))
                with store.tx() as c: payload=candidate_message(c,batch)
                queue(update,payload); await query.answer('후보를 다시 선택하세요'); return
            elif action=='batchreject':
                with store.tx() as c:
                    c.execute("UPDATE batches SET status='rejected' WHERE id=? AND day=? AND status='ready'",(int(parts[1]),kst_day()))
                    c.execute("UPDATE candidates SET status='rejected' WHERE batch_id=? AND status='available' AND EXISTS(SELECT 1 FROM batches WHERE id=? AND status='rejected')",(int(parts[1]),int(parts[1])))
                text='후보 묶음을 거절했습니다. 새 후보는 /newcandidates 로 명시적으로 요청하세요.'
            elif action in ('approve','reject','regenerate'):
                rid=int(parts[1]); rev=int(parts[2])
                if action=='regenerate':
                    r=store.row(rid)
                    if r['revision']!=rev or r['status']!='preview_ready': raise ValueError('Stale preview')
                    store.revise(rid,'기존 출처와 사실/창작 구분을 유지하며 문장과 구성을 새로 작성',config.integer('MAX_CONTENT_REVISIONS',3))
                else: store.decide(rid,rev,action=='approve',confirm_review=action=='approve')
                text='심의 처리를 저장했습니다. 실제 게시에는 서버의 별도 게시 허용 설정이 필요합니다.'
            else: raise ValueError('Unknown callback')
            await query.answer('접수 완료')
            queue(update,{'text':text})
        except (ValueError,IndexError,TypeError) as exc:
            await query.answer('현재 단계 또는 버전에서 처리할 수 없는 요청입니다.',show_alert=True)

    async def revision_message(update,context):
        if not authorized(update): return
        try:
            rev=store.apply_revision(str(update.effective_user.id),update.message.text,
                                     f'natural-revision:{update.update_id}',config.integer('MAX_CONTENT_REVISIONS',3))
            queue(update,{'text':f'수정 요청을 저장했습니다. 새 버전 v{rev}을 준비합니다.'})
        except (ValueError,TypeError):
            queue(update,{'text':'수정 요청을 적용하지 못했습니다. 현재 기획 수정/이미지 수정 버튼을 선택하고 1–1000자로 보내주세요.'})

    async def cancel_revision(update,context):
        if not authorized(update): return
        with store.tx() as c: c.execute('DELETE FROM conversations WHERE user_key=?',(str(update.effective_user.id),))
        queue(update,{'text':'수정 입력 대기를 취소했습니다.'})

    async def error(update,context):
        # Do not log HTTP request objects or provider exception strings (tokens in URLs).
        if update and authorized(update): queue(update,{'text':'처리 오류가 발생했습니다. /status 확인 후 관리자에게 작업 ID를 전달하세요.'})

    app=ApplicationBuilder().token(e['TELEGRAM_BOT_TOKEN']).build()
    for name in ('whoami','start','candidates','newcandidates','images','photos','status','preview','revise','review','acceptdraft','retry','resend'):
        app.add_handler(CommandHandler(name,command))
    app.add_handler(CallbackQueryHandler(callback,pattern=r'^(photopick|candidate|batchregen|batchreject|planapprove|planedit|imageedit|back|approve|reject|regenerate):'))
    app.add_handler(CommandHandler('cancelrevision',cancel_revision))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,revision_message))
    app.add_error_handler(error)
    return app


def main():
    import logging
    from .preflight import ConfigurationError
    from .safe_logging import configure_logging
    logging.getLogger('httpx').setLevel(logging.WARNING)
    try: config=Config.load()
    except Exception:
        raise SystemExit('운영 환경파일을 읽지 못했습니다. 비밀값을 출력하지 않고 중단합니다.') from None
    configure_logging(config.env)
    try:
        build_app(config).run_polling(drop_pending_updates=False,bootstrap_retries=0)
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from None
    except Exception as exc:
        raise SystemExit(f'Telegram 리스너 시작/수신 실패 ({type(exc).__name__}). 인증·연결 상태를 확인하세요. 비밀값은 출력하지 않습니다.') from None
