"""Meta Graph API with Facebook Login only; no unofficial login automation."""
import re
import requests
from .adapters import ExternalError


class Instagram:
    def __init__(self,config,http=requests):
        self.config=config; self.http=http

    def enabled(self):
        e=self.config.env
        return e.get('ENABLE_EXTERNAL_CALLS')=='1' and e.get('INSTAGRAM_PUBLISH_ENABLED')=='1' and all(e.get(k) for k in ('META_ACCESS_TOKEN','META_APP_ID','META_APP_ACCESS_TOKEN','INSTAGRAM_ACCOUNT_ID','META_PAGE_ID','META_GRAPH_VERSION'))

    def request(self,method,path,**params):
        self.config.require_external()
        if not self.enabled(): raise ExternalError('Instagram disabled')
        version=self.config.env['META_GRAPH_VERSION']
        if not re.fullmatch(r'v\d+\.\d+',version): raise ExternalError('Invalid configured Graph version')
        if not re.fullmatch(r'[A-Za-z0-9_/]+',path): raise ExternalError('Invalid Graph path')
        token=params.pop('_token',self.config.env['META_ACCESS_TOKEN'])
        try:
            response=self.http.request(method,f'https://graph.facebook.com/{version}/{path}',headers={'Authorization':'Bearer '+token},**({'params':params} if method=='GET' else {'data':params}),timeout=40)
            response.raise_for_status(); data=response.json()
            if 'error' in data: raise ExternalError('Meta rejected request')
            return data
        except Exception:
            raise ExternalError('Meta request failed; inspect durable stage before retry') from None

    def preflight(self):
        import time
        e=self.config.env
        info=self.request('GET','debug_token',input_token=e['META_ACCESS_TOKEN'],_token=e['META_APP_ACCESS_TOKEN']).get('data',{})
        required={'instagram_basic','instagram_content_publish','pages_read_engagement'}
        if not info.get('is_valid') or str(info.get('app_id'))!=e['META_APP_ID'] or not required<=set(info.get('scopes',[])):
            raise ExternalError('Token/app/scopes validation failed')
        for field in ('expires_at','data_access_expires_at'):
            if info.get(field) and info[field]<=time.time()+600: raise ExternalError('Token expires too soon')
        page=self.request('GET',e['META_PAGE_ID'],fields='instagram_business_account')
        if str(page.get('instagram_business_account',{}).get('id'))!=e['INSTAGRAM_ACCOUNT_ID']:
            raise ExternalError('Page is not linked to configured professional account')
        profile=self.request('GET',e['INSTAGRAM_ACCOUNT_ID'],fields='id,username,account_type')
        if profile.get('account_type') not in ('BUSINESS','MEDIA_CREATOR') or str(profile.get('id'))!=e['INSTAGRAM_ACCOUNT_ID']:
            raise ExternalError('Professional account required')
        limits=self.request('GET',e['INSTAGRAM_ACCOUNT_ID']+'/content_publishing_limit',fields='quota_usage,config')
        for row in limits.get('data',[]):
            cap=row.get('config',{}).get('quota_total')
            if cap is not None and row.get('quota_usage',0)>=cap: raise ExternalError('Publishing quota reached')
        return {'valid':True,'account_id':profile['id']}

    def child(self,url):
        return self.request('POST',self.config.env['INSTAGRAM_ACCOUNT_ID']+'/media',image_url=url,is_carousel_item='true')

    def carousel(self,children,caption):
        return self.request('POST',self.config.env['INSTAGRAM_ACCOUNT_ID']+'/media',media_type='CAROUSEL',children=','.join(children),caption=caption)

    def ready(self,container):
        # One bounded check. Not-ready resumes this read step, never creates a new container.
        result=self.request('GET',container,fields='status_code')
        if result.get('status_code')!='FINISHED': raise ExternalError('Container not finished; resume read after inspection')
        return {'ready':True}

    def publish(self,container):
        return self.request('POST',self.config.env['INSTAGRAM_ACCOUNT_ID']+'/media_publish',creation_id=container)

    def permalink(self, media_id):
        from .content import safe_https
        result=self.request('GET',media_id,fields='permalink,timestamp')
        url=result.get('permalink','')
        if not safe_https(url) or not url.startswith('https://www.instagram.com/'):
            raise ExternalError('Published URL unavailable; publication will not be repeated')
        return result
