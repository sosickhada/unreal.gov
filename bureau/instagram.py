"""Instagram API with Instagram Login only; no unofficial login automation."""
import re
import requests
from .adapters import ExternalError


class Instagram:
    def __init__(self,config,http=requests):
        self.config=config; self.http=http

    REQUIRED = ('IG_ACCESS_TOKEN','IG_ACCOUNT_ID','IG_GRAPH_VERSION')

    def missing_settings(self):
        return [key for key in self.REQUIRED if not self.config.env.get(key)]

    def enabled(self):
        e=self.config.env
        return e.get('ENABLE_EXTERNAL_CALLS')=='1' and e.get('INSTAGRAM_PUBLISH_ENABLED')=='1' and not self.missing_settings()

    def request(self,method,path,**params):
        self.config.require_external()
        if self.missing_settings(): raise ExternalError('Missing Meta settings: '+', '.join(self.missing_settings()))
        if method not in ('GET','POST'): raise ExternalError('Unsupported Meta method')
        if method!='GET' and not self.enabled(): raise ExternalError('Instagram publishing disabled')
        version=self.config.env['IG_GRAPH_VERSION']
        if not re.fullmatch(r'v\d+\.\d+',version): raise ExternalError('Invalid configured Graph version')
        if not re.fullmatch(r'[A-Za-z0-9_/]+',path): raise ExternalError('Invalid Graph path')
        token=params.pop('_token',self.config.env['IG_ACCESS_TOKEN'])
        try:
            response=self.http.request(method,f'https://graph.instagram.com/{version}/{path}',headers={'Authorization':'Bearer '+token},**({'params':params} if method=='GET' else {'data':params}),timeout=40)
            response.raise_for_status(); data=response.json()
            if 'error' in data: raise ExternalError('Meta rejected request')
            return data
        except Exception:
            raise ExternalError('Meta request failed; inspect durable stage before retry') from None

    def preflight(self):
        e=self.config.env
        profile=self.request('GET','me',fields='user_id,username,account_type')
        account=str(profile.get('user_id',''))
        if not account or account!=e['IG_ACCOUNT_ID']:
            raise ExternalError('Instagram Login user_id does not match IG_ACCOUNT_ID')
        if profile.get('account_type') not in ('BUSINESS','MEDIA_CREATOR'):
            raise ExternalError('Professional account required')
        import hashlib, json
        from pathlib import Path
        evidence_path=Path(self.config.db).parent/'data'/'instagram-grant.json'
        try: evidence=json.loads(evidence_path.read_text())
        except (OSError,ValueError): raise ExternalError('Instagram container grant evidence missing') from None
        if evidence.get('token_sha256')!=hashlib.sha256(e['IG_ACCESS_TOKEN'].encode()).hexdigest() or evidence.get('account_id')!=account or not evidence.get('container_id'):
            raise ExternalError('Instagram grant evidence does not match current token/account')
        quota=self.publishing_limit()['data']
        if not quota or quota[0].get('quota_usage',100)>=quota[0].get('config',{}).get('quota_total',0):
            raise ExternalError('Instagram publishing quota unavailable or exhausted')
        return {'valid':True,'permission_evidence':'unpublished_container_created','quota':quota}

    def assert_approval(self, store, record_id, revision):
        from .publish_review import assert_approved
        assert_approved(store,record_id,revision,self.config.env['IG_ACCOUNT_ID'])

    def connection_status(self):
        """Read-only connectivity is separate from authorization to publish."""
        import time
        profile=self.request('GET','me',fields='user_id,username,account_type')
        account=str(profile.get('user_id',''))
        if account!=self.config.env['IG_ACCOUNT_ID']:
            raise ExternalError('Instagram Login user_id does not match IG_ACCOUNT_ID')
        expiry=self.config.env.get('IG_TOKEN_EXPIRES_AT','')
        try:
            self.preflight();verified=True
        except ExternalError:
            verified=False
        return {'authenticated':True,'account_id':account,'username':profile.get('username'),
                'account_type':profile.get('account_type'),
                'permissions':{'instagram_business_basic':'profile_access_confirmed; grant_list_unverified',
                               'instagram_business_content_publish':'container_creation_confirmed' if verified else 'unverified'},
                'app_mode':'unverified','tester_role':'unverified','app_review':'unverified',
                'expires_at':int(expiry) if expiry.isdigit() else None,
                'expiry_source':'operator_supplied; not introspected' if expiry.isdigit() else 'unknown',
                'expired_by_record':int(expiry)<=time.time() if expiry.isdigit() else None,
                'ready_to_publish':verified and self.enabled(),
                'container_creation_verified':verified}

    def publishing_limit(self):
        """Read-only diagnostic; quota access is not proof of a publish grant."""
        result=self.request('GET',self.config.env['IG_ACCOUNT_ID']+'/content_publishing_limit',fields='config,quota_usage')
        return {'data':result.get('data',[]),'publish_permission_verified':False}

    def child(self,url):
        return self.request('POST',self.config.env['IG_ACCOUNT_ID']+'/media',image_url=url,is_carousel_item='true')

    def carousel(self,children,caption):
        if not 2<=len(children)<=10 or len(set(children))!=len(children):
            raise ExternalError('Carousel requires 2–10 distinct child containers')
        return self.request('POST',self.config.env['IG_ACCOUNT_ID']+'/media',media_type='CAROUSEL',children=','.join(children),caption=caption)

    def ready(self,container):
        # One bounded check. Not-ready resumes this read step, never creates a new container.
        result=self.request('GET',container,fields='status_code')
        if result.get('status_code')!='FINISHED': raise ExternalError('Container not finished; resume read after inspection')
        return {'ready':True}

    def publish(self,container):
        return self.request('POST',self.config.env['IG_ACCOUNT_ID']+'/media_publish',creation_id=container)

    def permalink(self, media_id):
        from .content import safe_https
        result=self.request('GET',media_id,fields='permalink,timestamp')
        url=result.get('permalink','')
        if not safe_https(url) or not url.startswith('https://www.instagram.com/'):
            raise ExternalError('Published URL unavailable; publication will not be repeated')
        return result
