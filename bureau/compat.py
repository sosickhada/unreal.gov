from .config import Config
from .store import Store


def enqueue(kind,rid):
    config=Config.load();store=Store(config.db);row=store.row(rid)
    if kind=='revise':
        revision=store.revise(rid,'관리자가 요청한 원고 및 카드뉴스 재생성',config.integer('MAX_CONTENT_REVISIONS',3))
        print('Revision queued',rid,revision)
        return
    required={'draft':('selected','revision_requested'),'render':('draft_ready',)}
    if row['status'] not in required[kind]: raise ValueError('Wrong content state')
    with store.tx() as c:
        jid=store.enqueue(c,f'{kind}:{rid}:{row["revision"]}',kind,{'id':rid,'revision':row['revision']})
    print('Queued job',jid)
