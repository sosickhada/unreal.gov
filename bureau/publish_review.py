"""Fail-closed Instagram review UI. A diagnostic never grants publication."""
def blocked_review(record_id, revision, caption, reason):
    return {
        'text':('Instagram 게시 준비 확인\n게시 계정: @un_real_korea\n이미지: 5장\n'
                f'게시물: {record_id} / 버전: {revision}\n상태: 게시 차단\n사유: {reason}\n\n'
                '승인 버튼은 게시 권한과 이미지 수집 검증 후 제공됩니다.\n\n캡션:\n'+caption)[:4000],
        'reply_markup':{'inline_keyboard':[
            [{'text':'🔒 Instagram 게시 승인 — 차단됨','callback_data':f'igblocked:{record_id}:{revision}'}],
            [{'text':'게시 상태 확인','callback_data':f'igblocked:{record_id}:{revision}'}],
            [{'text':'미리보기 닫기','callback_data':f'igclose:{record_id}:{revision}'}]]}}
