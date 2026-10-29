import json
import hashlib
from pathlib import Path
from urllib.parse import urlparse
import requests
from .content import safe_https


class ExternalError(RuntimeError):
    """Safe error: never exposes provider response, credentials or request URLs."""


class Claude:
    def __init__(self, config):
        self.config=config

    def validate(self):
        from .preflight import claude_settings
        return claude_settings(self.config.env)

    def generate(self, prompt, maximum):
        self.validate()
        self.config.require_external()
        from anthropic import Anthropic
        env=self.config.env
        if not env.get('ANTHROPIC_API_KEY') or not env.get('CLAUDE_MODEL'):
            raise ExternalError('Claude credentials/model missing')
        try:
            # One SDK attempt only. An unknown response must not trigger another paid call.
            if len(prompt.encode('utf-8'))>24000 or len(prompt.encode('utf-8'))+maximum>self.config.integer('TOKENS_RESERVED_PER_CALL',30000):
                raise ExternalError('Prompt exceeds reserved input budget')
            response=Anthropic(api_key=env['ANTHROPIC_API_KEY'],timeout=60,max_retries=0).messages.create(
                model=env['CLAUDE_MODEL'],max_tokens=maximum,messages=[{'role':'user','content':prompt}])
            if response.stop_reason!='end_turn':
                raise ExternalError('Claude response incomplete')
            raw='\n'.join(b.text for b in response.content if b.type=='text')
            return {'raw':raw,'input_tokens':response.usage.input_tokens,'output_tokens':response.usage.output_tokens}
        except Exception:
            raise ExternalError('Claude request failed or response uncertain') from None


class Media:
    def __init__(self, config):
        self.config=config

    def render(self, draft, rid, revision):
        from PIL import Image
        root=Path(self.config.env.get('RENDER_DIR') or self.config.env.get('IMAGE_DIR','/opt/unreal.gov/public/images'))
        root.mkdir(parents=True,exist_ok=True)
        import os, signal, subprocess, sys, tempfile
        with tempfile.TemporaryDirectory(prefix='unreal-render-job-') as tmp:
            source=Path(tmp)/'draft.json';target=Path(tmp)/'result.json'
            source.write_text(json.dumps(draft,ensure_ascii=False))
            render_env=dict(os.environ)
            render_env['UNREAL_BROWSER_PROFILE_DIR']=self.config.env.get('UNREAL_BROWSER_PROFILE_DIR','/tmp')
            render_env['UNREAL_FONT_TIMEOUT_SECONDS']=str(self.config.integer('FONT_TIMEOUT_SECONDS',45))
            if self.config.env.get('RENDER_TRACE_DIR'):
                trace_root=Path(self.config.env['RENDER_TRACE_DIR']);trace_root.mkdir(parents=True,exist_ok=True)
                render_env['UNREAL_RENDER_TRACE']=str((trace_root/f'{rid}-v{revision}-trace.json').resolve())
            process=subprocess.Popen([sys.executable,'-m','bureau.render_task',str(source),str(root/f'unreal-case-{rid}-v{revision}'),str(target)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,env=render_env)
            try:
                code=process.wait(timeout=self.config.integer('RENDER_TIMEOUT_SECONDS',180))
            except subprocess.TimeoutExpired:
                terminate_render_tree(process.pid)
                process.wait()
                if not target.is_file():
                    raise ExternalError('Figma renderer exceeded hard deadline; child group terminated') from None
                code=0  # Completed manifest survives a bounded shutdown failure.
            if code!=0:
                terminate_render_tree(process.pid)
            if not target.is_file():
                raise ExternalError('Figma render failed; run bounded offline smoke check')
            paths=json.loads(target.read_text())
        if len(paths) not in (4,5):
            raise ValueError('Expected 4–5 Figma pages')
        for p in paths:
            with Image.open(p) as im:
                if im.size!=(1080,1350) or im.format!='PNG':
                    raise ValueError('Incorrect rendered dimensions')
        # PNG remains the approved render; JPEG is the official publishing derivative.
        jpgs=[]
        for p in paths:
            target=Path(p).with_suffix('.jpg')
            with Image.open(p) as im:
                im.convert('RGB').save(target,'JPEG',quality=95)
            if target.stat().st_size>8_000_000:
                raise ValueError('Publishing JPEG exceeds size limit')
            jpgs.append(str(target))
        base=self.config.env.get('PUBLIC_BASE_URL','').rstrip('/')
        if not safe_https(base):
            raise ValueError('PUBLIC_BASE_URL must be HTTPS')
        return {'pngs':paths,'files':jpgs,'urls':[base+'/images/'+Path(p).name for p in jpgs],
                'sha256':[hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in jpgs],
                'license_review_required':True,'face_review_required':True,'source':'existing_approved_figma_assets'}

    def expose(self, media):
        """Explicit operational permission is required before copying to the public root."""
        self.config.require_external()
        if self.config.env.get('ENABLE_PUBLIC_MEDIA')!='1':
            raise ExternalError('Public media exposure disabled')
        root=Path(self.config.env.get('IMAGE_DIR','/opt/unreal.gov/public/images'))
        root.mkdir(parents=True,exist_ok=True)
        for source,expected in zip(media['files'],media['sha256'],strict=True):
            data=Path(source).read_bytes()
            if hashlib.sha256(data).hexdigest()!=expected: raise ValueError('Local publishing asset changed')
            target=root/Path(source).name
            # Publish a complete file atomically; never replace different existing bytes.
            import tempfile,os
            with tempfile.NamedTemporaryFile(dir=root,prefix='.pending-',delete=False) as pending:
                pending.write(data);pending_path=Path(pending.name)
            try:
                pending_path.chmod(0o644)
                try: os.link(pending_path,target)
                except FileExistsError:
                    if target.read_bytes()!=data: raise ValueError('Existing public file conflicts with this revision')
            finally: pending_path.unlink(missing_ok=True)
        return {'exposed':True}

    def verify(self, media):
        self.config.require_external()
        expected=urlparse(self.config.env.get('PUBLIC_BASE_URL','')).netloc
        for url in media['urls']:
            if not safe_https(url) or urlparse(url).netloc!=expected:
                raise ValueError('Untrusted public image URL')
            try:
                from io import BytesIO
                from PIL import Image
                response=requests.get(url,timeout=20,allow_redirects=False)
                response.raise_for_status()
                if response.status_code!=200: raise ValueError('Public redirect/non-200 response rejected')
                if not response.headers.get('Content-Type','').startswith('image/jpeg') or len(response.content)>8_000_000:
                    raise ValueError('Invalid public image response')
                with Image.open(BytesIO(response.content)) as im:
                    if im.size!=(1080,1350) or im.format!='JPEG':
                        raise ValueError('Invalid public image dimensions/format')
                # Reject stale/mismapped files, not merely a matching Content-Type.
                index=media['urls'].index(url)
                if hashlib.sha256(response.content).hexdigest()!=media['sha256'][index] or response.content!=Path(media['files'][index]).read_bytes():
                    raise ValueError('Public bytes differ from approved local asset')
            except Exception:
                raise ExternalError('Public image validation failed') from None
        return {'verified':True}


class Telegram:
    def __init__(self, config):
        self.config=config

    def send(self, payload):
        self.config.require_external()
        env=self.config.env
        if not env.get('TELEGRAM_BOT_TOKEN') or not env.get('TELEGRAM_CHAT_ID'):
            raise ExternalError('Telegram credentials missing')
        if payload.get('files') and payload.get('sha256'):
            if len(payload['files'])!=len(payload['sha256']): raise ExternalError('Invalid album hash count')
            for path,expected in zip(payload['files'],payload['sha256']):
                if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=expected:
                    raise ExternalError('Preview asset changed; delivery blocked')
        base='https://api.telegram.org/bot'+env['TELEGRAM_BOT_TOKEN']
        handles=[]
        try:
            if payload.get('files'):
                media=[]; files={}
                for i,path in enumerate(payload['files']):
                    h=open(path,'rb'); handles.append(h); files[f'p{i}']=h
                    item={'type':'photo','media':f'attach://p{i}'}
                    if i==0:
                        item['caption']=payload.get('text','')[:1000]
                    media.append(item)
                response=requests.post(base+'/sendMediaGroup',data={'chat_id':env['TELEGRAM_CHAT_ID'],'media':json.dumps(media)},files=files,timeout=90)
            else:
                data={'chat_id':env['TELEGRAM_CHAT_ID'],'text':payload['text'][:4000],'disable_web_page_preview':True}
                if payload.get('reply_markup'):
                    data['reply_markup']=payload['reply_markup']
                response=requests.post(base+'/sendMessage',json=data,timeout=30)
            response.raise_for_status(); result=response.json()
            if not result.get('ok'):
                raise ExternalError('Telegram rejected delivery')
            rows=result['result'] if isinstance(result['result'],list) else [result['result']]
            return [r['message_id'] for r in rows]
        except Exception:
            raise ExternalError('Telegram delivery uncertain; inspect before replay') from None
        finally:
            for h in handles:
                h.close()


def terminate_render_tree(pid):
    """Playwright can detach Chromium; kill descendants before the parent group."""
    import os, signal
    descendants=[]
    def collect(parent):
        try:
            children=Path(f'/proc/{parent}/task/{parent}/children').read_text().split()
        except (FileNotFoundError,PermissionError):
            return
        for child in children:
            child=int(child)
            descendants.append(child)
            collect(child)
    collect(pid)
    for child in reversed(descendants):
        try: os.kill(child,signal.SIGKILL)
        except ProcessLookupError: pass
    try: os.killpg(pid,signal.SIGKILL)
    except ProcessLookupError: pass
