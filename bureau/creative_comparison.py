"""Explicitly labelled editorial fixtures; never a live model quality benchmark."""
import json
from pathlib import Path
from . import creative as c2

FIXTURES=Path(__file__).resolve().parents[1]/'tests/fixtures/creative_v2_cases.json'


def compare(path=FIXTURES):
    corpus=json.loads(Path(path).read_text())
    if corpus.get('test_only') is not True:raise ValueError('Comparison corpus must be test-only')
    results=[]
    for case in corpus['cases']:
        if not case.get('test_only') or not case['after'].get('test_only'):raise ValueError('Unlabelled test content')
        c2.validate_candidate(case['candidate']);c2.validate_conflict(case['plan'],case['candidate'],case['source_feedback'])
        options=c2.validate_verdicts(case['verdicts'],case['plan']);c2.ground_draft(case['after'],case['plan'],options)
        before=case['before'];after=case['after']
        old_verdict=before['slides'][2].get('body','')
        selected=next(v for v in options if v['id']==after['verdict_id'])
        before_copy=' '.join(s.get('body','') for s in before['slides'])
        after_copy=' '.join(s['body'] for s in after['slides'])
        markers=('本','본 위원회','의견이 나뉘','권고한다','이 사건은 가상','본 처분은 가상')
        results.append({'case':case['id'],'test_only':True,'before_provenance':case['before_kind'],
            'before':before,'after':after,'verdict_candidates':options,
            'ruling_comparison':{'before':old_verdict,'after':selected['order'],'type':selected['type'],'logic':selected['logic']},
            'ending_comparison':{'before':'고정 브랜드 엔딩; 새 후폭풍 원고 없음','after':after['slides'][-1]['body']},
            'institutional_mechanism':selected['logic'],
            'expression_counts':{m:{'before':before_copy.count(m),'after':after_copy.count(m)} for m in markers},
            'engagement_point':case['candidate']['issue'],
            'human_review_needed':['실제 공감·논쟁 가능성','판정이 억지인지','후폭풍이 웃기는지','자연스러운 한국어'],
            'quality_claim':'handwritten editorial alternative; no live-model or audience-success claim'})
    return {'test_only':True,'api_calls':0,'paid_calls':0,'real_publications':0,'provenance':corpus['provenance'],
            'case_count':len(results),'results':results}


def markdown(report):
    lines=['# 창작 엔진 2.0 오프라인 비교','',
        '모든 개선안과 신규 소재는 테스트 전용 편집 예시다. 유료 모델 생성·독자 반응 검증이 아니다.',
        '기존 3건은 저장된 Claude 원고, 신규 5건의 구형안은 구조 비교용 수기 baseline이다.','']
    for item in report['results']:
        lines+=['## '+item['case']+' · 테스트 전용','',
            '- 기존 판정: '+item['ruling_comparison']['before'].replace('\n',' '),
            '- 개선 판정: '+item['ruling_comparison']['after'],
            '- 후폭풍: '+item['ending_comparison']['after'],
            '- 기관 논리: '+item['institutional_mechanism'],
            '- 의견이 갈릴 지점: '+item['engagement_point'],'',
            '판정 후보:',*['- '+v['type']+' / '+v['order']+' → '+v['side_effect'] for v in item['verdict_candidates']],'']
    return '\n'.join(lines)
