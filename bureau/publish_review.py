"""Instagram diagnostics and content-bound explicit publication approval."""
def blocked_review(record_id, revision, caption, reason):
    return {
        'text':('Instagram 게시 준비 확인\n게시 계정: @un_real_korea\n이미지: 5장\n'
                f'게시물: {record_id} / 버전: {revision}\n상태: 게시 차단\n사유: {reason}\n\n'
                '승인 버튼은 게시 권한과 이미지 수집 검증 후 제공됩니다.\n\n캡션:\n'+caption)[:4000],
        'reply_markup':{'inline_keyboard':[
            [{'text':'🔒 Instagram 게시 승인 — 차단됨','callback_data':f'igblocked:{record_id}:{revision}'}],
            [{'text':'게시 상태 확인','callback_data':f'igblocked:{record_id}:{revision}'}],
            [{'text':'미리보기 닫기','callback_data':f'igclose:{record_id}:{revision}'}]]}}


def fingerprint(c, rid, revision, account):
    import json
    from .store import digest
    r=c.execute('SELECT revision,draft_json FROM selections WHERE id=?',(rid,)).fetchone()
    a=c.execute('SELECT payload FROM assets WHERE selection_id=? AND revision=?',(rid,revision)).fetchone()
    if not r or r['revision']!=revision or not a: raise ValueError('Review version changed')
    return digest({'account':account,'draft':json.loads(r['draft_json']),'assets':json.loads(a['payload'])})


def prepare_review(store, rid, revision, account):
    import json
    review_note=''
    with store.tx() as c:
        r=c.execute('SELECT * FROM selections WHERE id=?',(rid,)).fetchone()
        if r['published_id'] or r['status'] not in ('preview_ready','publish_waiting'): raise ValueError('Not awaiting approval')
        fp=fingerprint(c,rid,revision,account)
        c.execute('INSERT OR REPLACE INTO instagram_reviews VALUES(?,?,?,?,0)',(rid,revision,account,fp))
        # Prior approval cannot authorize this new review.
        c.execute("UPDATE selections SET status='preview_ready',approved_revision=NULL,reviewed_revision=NULL WHERE id=?",(rid,))
        draft=json.loads(r['draft_json']);caption=draft['caption']
        if draft.get('publication_kind')=='official':
            from .release import validate_official
            media=json.loads(c.execute('SELECT payload FROM assets WHERE selection_id=? AND revision=?',(rid,revision)).fetchone()[0])
            validate_official(draft,media)
            review_note='사진: Pexels License · https://www.pexels.com/license/\n최종 승인은 원고·사진 관련성·라이선스·초상권 검토를 포함합니다.\n\n'
    return {'text':f'Instagram 공개 게시 승인 요청\n게시 계정: @un_real_korea ({account})\n카드뉴스 5장 · 게시물 {rid} v{revision}\n미리보기 5장과 캡션을 검토한 후 승인하세요. 승인하면 공개 게시됩니다.\n\n'+review_note+'캡션:\n'+caption,
            'reply_markup':{'inline_keyboard':[[{'text':'✅ Instagram 공개 게시 승인','callback_data':f'igapprove:{rid}:{revision}:{fp[:16]}'}],[{'text':'게시 취소','callback_data':f'igcancel:{rid}:{revision}:{fp[:16]}'}]]}}


def decide_review(store,rid,revision,short,approve):
    with store.tx() as c:
        review=c.execute('SELECT * FROM instagram_reviews WHERE selection_id=?',(rid,)).fetchone()
        r=c.execute('SELECT * FROM selections WHERE id=?',(rid,)).fetchone()
        if not review or review['revision']!=revision or review['fingerprint'][:16]!=short or r['status']!='preview_ready': raise ValueError('Stale review')
        if fingerprint(c,rid,revision,review['account_id'])!=review['fingerprint']: raise ValueError('Content changed; request a new approval')
        c.execute('UPDATE instagram_reviews SET approved=? WHERE selection_id=?',(int(approve),rid))
        c.execute('UPDATE selections SET status=?,approved_revision=?,reviewed_revision=? WHERE id=?',('approved' if approve else 'rejected',revision if approve else None,revision if approve else None,rid))
        if approve: store.enqueue(c,f'publish:{rid}:{revision}:ig:{short}','publish',{'id':rid,'revision':revision})
        store.event(c,rid,'instagram_approved' if approve else 'instagram_cancelled',review['fingerprint'])


def assert_approved(store,rid,revision,account):
    import hashlib
    from pathlib import Path
    with store.tx() as c:
        review=c.execute('SELECT * FROM instagram_reviews WHERE selection_id=?',(rid,)).fetchone()
        if not review or not review['approved'] or review['revision']!=revision or review['account_id']!=account or fingerprint(c,rid,revision,account)!=review['fingerprint']:
            raise ValueError('Exact Instagram content approval required')
        import json
        a=json.loads(c.execute('SELECT payload FROM assets WHERE selection_id=? AND revision=?',(rid,revision)).fetchone()[0])
        for path,sha in zip(a['files'],a['sha256'],strict=True):
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha: raise ValueError('Approved image changed; reapproval required')
