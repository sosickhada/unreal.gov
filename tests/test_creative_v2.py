import asyncio
from copy import deepcopy
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch,AsyncMock
from bureau.config import Config
from bureau.store import Store,now,kst_day
from bureau.engine import Engine,Waiting
from bureau import creative as c2
from bureau.creative_workflow import CreativeWorkflow
from bureau.creative_comparison import compare

CASES=json.loads((Path(__file__).parent/'fixtures/creative_v2_cases.json').read_text())['cases']


def editor(draft,accepted=True):
    quote=next(s['body'] for s in draft['slides'] if s['body'])
    return {'approved':accepted,'scores':{k:4 if accepted else 2 for k in c2.SCORES},
        'factual_consistency':True,'no_identifying_people':True,'verdict_linked':True,
        'boring_sentence':quote,'explanatory_sentence':quote,
        'dropout_scene':{'slide':2,'reason':'설명 문장의 밀도가 높아 독자의 속도가 떨어질 수 있다'},
        'stronger_conflict':'A와 B가 같은 표현을 다르게 해석하는 장면을 앞세운다',
        'predictable_verdict_reason':'행동의 구체적 접수 규칙이 실제 후폭풍으로 이어지는지 검토한다',
        'ending_improvement':'조치가 만든 새로운 생활 변화 한 장면으로 마무리한다'}


class FakeCreative:
    def __init__(self,case=CASES[0],rejects=0,fail_stage=None):
        self.case=deepcopy(case);self.rejects=rejects;self.fail_stage=fail_stage;self.calls=[];self.last_draft=None
    def validate(self):pass
    def generate_role(self,stage,system,user,maximum,model=None):
        self.calls.append((stage,model));data=json.loads(user)
        if self.fail_stage==stage:raise TimeoutError('SENSITIVE_PROVIDER_EXCEPTION')
        if stage=='ideas':
            items=[deepcopy(c['candidate']) for c in CASES]
            for i,domain in enumerate(('friends','relationships','work','appointments')):
                item=deepcopy(CASES[i]['candidate']);item['domain']=domain;item['conflict_key']+='clone'
                items.append(item)
            result={'candidates':items}
        elif stage=='conflict':result=self.case['plan']
        elif stage=='verdict':result=self.case['verdicts']
        elif stage=='draft':
            result=deepcopy(self.case['after'])
            if data.get('editor_feedback'):
                option=self.case['verdicts']['options'][1]
                result['verdict_id']=option['id'];result['slides'][-2]['body']=option['order'];result['slides'][-1]['body']=option['side_effect']
            self.last_draft=result
        elif stage=='editor':
            result=editor(self.last_draft,self.rejects<=0);self.rejects-=1
        elif stage=='image_brief':result={'image_queries':{'content':'unbranded laundry bottle on shelf','resolution_extra':'cardboard parcel by apartment door'}}
        else:raise AssertionError(stage)
        return {'raw':json.dumps(result,ensure_ascii=False),'input_tokens':100,'output_tokens':200,'model_id':model}


class CreativeV2Tests(unittest.TestCase):
    def setUp(self):
        self.net=patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN'));self.net.start()
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.cfg=Config(self.root/'db',{'ENABLE_EXTERNAL_CALLS':'1','CLAUDE_MODEL':'claude-haiku-5-5','CONTENT_ENGINE_VERSION':'2','REQUIRE_TOPIC_IMAGE':'0'})
        self.store=Store(self.cfg.db);self.store.migrate()
    def tearDown(self):self.net.stop();self.tmp.cleanup()
    def seed(self,case=CASES[0]):
        p=case['candidate'];source={'creative_version':2,'creative_brief':p,'title':p['title'],'summary':p['objective'],'hook':p['hook'],'empathy':p['empathy'],'share_reason':p['share_reason'],'satire_angle':'판정 미정','source_url':None}
        with self.store.tx() as c:
            batch=c.execute("INSERT INTO batches(day,generation,status,created_at) VALUES(?,0,'ready',?)",(kst_day(),now())).lastrowid
            cid=c.execute('INSERT INTO candidates(batch_id,position,title,payload,created_at) VALUES(?,1,?,?,?)',(batch,p['title'],json.dumps(source),now())).lastrowid
        return self.store.select(cid)
    def engine(self,model):return Engine(self.cfg,claude=model,media=Mock(),telegram=Mock(),instagram=Mock())
    def test_eight_cases_are_explicit_editorial_fixtures_not_model_success(self):
        report=compare();self.assertEqual(report['case_count'],8);self.assertEqual(report['paid_calls'],0)
        self.assertEqual(len({c['after']['format'] for c in CASES}),6)
        for row in report['results']:
            self.assertTrue(row['test_only']);self.assertEqual(len(row['verdict_candidates']),3)
            self.assertNotEqual(row['ruling_comparison']['before'],row['ruling_comparison']['after'])
    def test_independent_editor_records_models_prompts_and_stops_before_images(self):
        rid=self.seed();ai=FakeCreative();e=self.engine(ai);self.assertTrue(e.run_one())
        self.assertEqual([x[0] for x in ai.calls],['conflict','verdict','draft','editor'])
        self.assertEqual(self.store.row(rid)['status'],'planning_review');e.media.render.assert_not_called()
        with self.store.tx() as c:
            rows=c.execute('SELECT * FROM creative_calls').fetchall();self.assertEqual(len(rows),4)
            self.assertTrue(all(r['prompt_version'].startswith(c2.VERSION) and len(r['request_sha256'])==64 for r in rows))
            self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE kind IN ('render','publish')").fetchone()[0],0)
            message=json.loads(c.execute("SELECT payload FROM outbox WHERE delivery_key LIKE 'creative-plan:%'").fetchone()[0])
            self.assertIn(CASES[0]['after']['slides'][-1]['body'],message['text'])
        self.store.accept_draft(rid,1)
        self.assertEqual(self.store.row(rid)['status'],'draft_ready')
    def test_rewrite_changes_ruling_and_side_effect_not_just_words(self):
        rid=self.seed();ai=FakeCreative(rejects=1);self.engine(ai).run_one()
        d=json.loads(self.store.row(rid)['draft_json'])
        self.assertEqual(d['verdict_id'],'v2');self.assertNotEqual(d['slides'][-1]['body'],CASES[0]['after']['slides'][-1]['body'])
        self.assertEqual(sum(s=='draft' for s,_ in ai.calls),2)
    def test_three_rejections_hold_and_never_render_or_publish(self):
        rid=self.seed();ai=FakeCreative(rejects=10);e=self.engine(ai);e.run_one()
        self.assertEqual(self.store.row(rid)['status'],'editorial_hold')
        self.assertEqual(sum(s=='draft' for s,_ in ai.calls),3)
        self.assertEqual(sum(s=='editor' for s,_ in ai.calls),3)
        e.media.render.assert_not_called();e.instagram.publish.assert_not_called()
        with self.assertRaises(ValueError):self.store.accept_draft(rid,1)
        with self.store.tx() as c:self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE kind='publish'").fetchone()[0],0)
    def test_uncertain_editor_call_cannot_be_replayed(self):
        self.seed();ai=FakeCreative(fail_stage='editor');e=self.engine(ai);e.run_one();self.assertFalse(e.run_one())
        from bureau.cli import resume
        with self.store.tx() as c:
            jid=c.execute('SELECT id FROM jobs').fetchone()[0]
            self.assertEqual(c.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()[0],'uncertain')
            self.assertEqual(c.execute("SELECT state FROM creative_calls WHERE stage='editor'").fetchone()[0],'uncertain')
        with self.assertRaises(ValueError):resume(self.store,jid)
    def test_model_routes_only_final_writer_editor_to_upper_tier(self):
        cfg=Config(self.cfg.db,dict(self.cfg.env,CLAUDE_DRAFT_MODEL='claude-sonnet-4-6',CLAUDE_EDITOR_MODEL='claude-opus-4-6'))
        self.assertEqual(c2.model_for(cfg,'ideas'),'claude-haiku-5-5')
        self.assertEqual(c2.model_for(cfg,'draft'),'claude-sonnet-4-6')
        with self.assertRaises(ValueError):c2.model_for(Config(cfg.db,dict(cfg.env,CLAUDE_IDEA_MODEL='claude-sonnet-4-6')),'ideas')
    def test_frozen_facts_examples_and_generic_verdicts_are_rejected(self):
        case=deepcopy(CASES[0]);case['plan']['facts']['objective']+=' 새 사실'
        with self.assertRaises(ValueError):c2.validate_conflict(case['plan'],case['candidate'])
        case=deepcopy(CASES[0]);case['candidate']['objective']='친구가 한 입 먹겠다며 케이크 절반을 먹었다.'
        with self.assertRaises(ValueError):c2.validate_candidate(case['candidate'])
        case=deepcopy(CASES[0]);case['verdicts']['options'][0]['order']='서로 양보할 것을 권고한다'
        with self.assertRaises(ValueError):c2.validate_verdicts(case['verdicts'],case['plan'])
    def test_high_scores_without_real_quotes_or_logic_do_not_pass(self):
        d=CASES[0]['after'];review=editor(d);review['boring_sentence']='원고에 없는 인용입니다.'
        with self.assertRaises(ValueError):c2.review_accepted(review,d)
        review=editor(d);review['factual_consistency']=False
        self.assertFalse(c2.review_accepted(review,d))
    def test_all_types_and_formats_have_real_contracts_and_appeal_requires_source(self):
        self.assertEqual(set(c2.VERDICT_TYPES),set('ABCDEFGHIJ'))
        for case in CASES:
            c2.validate_conflict(case['plan'],case['candidate'],case['source_feedback'])
            self.assertEqual(len(case['after']['slides']),5)
        with self.assertRaises(ValueError):c2.validate_conflict(CASES[-1]['plan'],CASES[-1]['candidate'],[])
    def test_domains_and_old_topic_repetition_filter(self):
        items=[deepcopy(c['candidate']) for c in CASES]
        chosen=c2.choose_candidates(items,[items[0]])
        self.assertNotIn(items[0],chosen);self.assertEqual(len({x['domain'] for x in chosen}),3)
        options=deepcopy(CASES[0]['verdicts']['options'])
        history=[{'format':'hearing','verdict_type':v['type']} for v in options[:2]]
        with self.assertRaises(ValueError):c2.select_verdict(options,history,'hearing')
        for v in options:v.update(fit=5,surprise=4,humor=4)
        self.assertEqual(c2.select_verdict(options,history,'hearing')['id'],'v3')
        options[2]['fit']=1
        with self.assertRaises(ValueError):c2.select_verdict(options,history,'hearing')
    def test_test_fixture_cannot_become_publication(self):
        from bureau.release import validate_official
        d=deepcopy(CASES[0]['after']);d['publication_kind']='official'
        with self.assertRaisesRegex(ValueError,'Test fixtures'):validate_official(d,{})
    def test_paid_pause_blocks_real_adapter_before_sdk(self):
        from bureau.adapters import Claude
        cfg=Config(self.cfg.db,dict(self.cfg.env,PAID_AI_CALLS_ENABLED='0'))
        with patch('anthropic.Anthropic') as sdk:
            with self.assertRaises(ValueError):Claude(cfg).generate_role('draft','system','user',100)
            sdk.assert_not_called()
    def test_resuming_different_model_or_prompt_is_not_a_new_paid_request(self):
        self.seed();job=self.store.claim();ai=FakeCreative();workflow=CreativeWorkflow(self.engine(ai))
        request={'plan':CASES[0]['plan']};workflow.call(job,'conflict',request)
        with self.assertRaises(Waiting):workflow.call(job,'conflict',dict(request,changed=True))
        self.assertEqual(len(ai.calls),1)
    def test_authorized_reconsideration_is_idempotent_and_preserves_published_parent(self):
        rid=self.seed();self.engine(FakeCreative()).run_one()
        with self.store.tx() as c:c.execute("UPDATE selections SET status='published',published_id='offline-parent' WHERE id=?",(rid,))
        sid=self.store.appeal(rid,'판정의 예외가 다른 대기자의 시간을 더 늘린다는 반론','update:1')
        self.assertEqual(self.store.appeal(rid,'동일 요청이 다시 전달되었습니다','update:1'),sid)
        self.assertNotEqual(rid,sid);self.assertEqual(self.store.row(rid)['published_id'],'offline-parent')
        with self.store.tx() as c:self.assertEqual(c.execute('SELECT count(*) FROM creative_appeals').fetchone()[0],1)
    def test_renderer_maps_five_distinct_roles_without_fixed_ending(self):
        from figma_renderer import expand_slides
        for case in CASES:
            pages=expand_slides(case['after']);self.assertEqual(len(pages),5)
            self.assertEqual([p[0] for p in pages],['cover','story','story','story','story'])
            self.assertEqual(pages[-1][1]['body'],case['after']['slides'][-1]['body'])

    def test_candidate_pipeline_persists_only_three_balanced_choices_without_verdicts(self):
        ai=FakeCreative();e=self.engine(ai);self.store.schedule();e.run_one()
        with self.store.tx() as c:
            rows=[json.loads(r[0]) for r in c.execute('SELECT payload FROM candidates')]
            self.assertEqual(len(rows),3);self.assertEqual(len({x['creative_brief']['domain'] for x in rows}),3)
            self.assertTrue(all('order' not in x['creative_brief'] for x in rows))
            self.assertEqual(c.execute('SELECT count(*) FROM idea_audits').fetchone()[0],12)
        self.assertEqual([s for s,_ in ai.calls],['ideas'])
    def test_images_require_human_plan_approval_and_test_content_never_enters_render(self):
        rid=self.seed();ai=FakeCreative();e=self.engine(ai);e.run_one()
        self.assertFalse(e.run_one());self.assertFalse(any(s=='image_brief' for s,_ in ai.calls))
        self.store.accept_draft(rid,1);e.run_one()
        e.media.render.assert_not_called();self.assertFalse(any(s=='image_brief' for s,_ in ai.calls))
        with self.store.tx() as c:self.assertEqual(c.execute("SELECT error_code FROM jobs WHERE kind='render'").fetchone()[0],'test_content_blocked')
    def test_editor_evidence_survives_image_revision_but_rejects_text_mutation(self):
        rid=self.seed();self.engine(FakeCreative()).run_one();d=json.loads(self.store.row(rid)['draft_json'])
        c2.assert_editorial_evidence(self.store,rid,1,d)
        d['image_queries']={'content':'photo one','resolution_extra':'photo two'}
        c2.assert_editorial_evidence(self.store,rid,2,d)
        d['slides'][-1]['body']='승인 이후 바뀐 결말입니다.'
        with self.assertRaises(ValueError):c2.assert_editorial_evidence(self.store,rid,2,d)
    def test_json_failure_has_bounded_rewrites_and_hold_not_an_approval(self):
        rid=self.seed();ai=FakeCreative();original=ai.generate_role
        def bad(stage,*args,**kwargs):
            if stage=='draft':ai.calls.append((stage,kwargs.get('model')));return {'raw':'not-json','input_tokens':1,'output_tokens':1}
            return original(stage,*args,**kwargs)
        ai.generate_role=bad;self.engine(ai).run_one()
        self.assertEqual(self.store.row(rid)['status'],'editorial_hold');self.assertEqual(sum(s=='draft' for s,_ in ai.calls),3)
        self.assertFalse(any(s=='editor' for s,_ in ai.calls))
    def test_editor_hold_can_take_explicit_feedback_and_create_a_new_unapproved_revision(self):
        rid=self.seed();self.engine(FakeCreative(rejects=9)).run_one()
        self.store.await_revision('11',rid,1,'plan');rev=self.store.apply_revision('11','판정의 책임을 접수 화면 쪽으로 옮기고 부작용을 바꿔주세요','feedback:1')
        self.assertEqual(rev,2);self.assertIsNone(self.store.row(rid)['approved_revision'])
        ai=FakeCreative();self.engine(ai).run_one();self.assertEqual(self.store.row(rid)['status'],'planning_review')
    def test_role_api_request_uses_distinct_system_user_and_correct_model_without_network(self):
        from bureau.adapters import Claude
        cfg=Config(self.cfg.db,dict(self.cfg.env,ANTHROPIC_API_KEY='offline-key',CLAUDE_DRAFT_MODEL='claude-sonnet-4-6'))
        response=NS(stop_reason='end_turn',content=[NS(type='text',text='{}')],usage=NS(input_tokens=4,output_tokens=5),model='claude-sonnet-4-6')
        with patch('anthropic.Anthropic') as sdk:
            sdk.return_value.messages.create.return_value=response
            result=Claude(cfg).generate_role('draft','brand role','frozen input',100)
            kw=sdk.return_value.messages.create.call_args.kwargs
            self.assertEqual(kw['model'],'claude-sonnet-4-6');self.assertEqual(kw['system'],'brand role')
            self.assertEqual(kw['messages'],[{'role':'user','content':'frozen input'}]);self.assertEqual(result['model_id'],'claude-sonnet-4-6')
            self.assertEqual(sdk.call_args.kwargs['max_retries'],0)
    def test_paid_call_cap_blocks_additional_stages(self):
        rid=self.seed();cfg=Config(self.cfg.db,dict(self.cfg.env,MAX_CLAUDE_CALLS_PER_DAY='1'));ai=FakeCreative();e=self.engine(ai);e.config=cfg;e.run_one()
        self.assertEqual(len(ai.calls),1)
        with self.store.tx() as c:self.assertEqual(c.execute('SELECT state FROM jobs').fetchone()[0],'waiting')
        self.assertNotEqual(self.store.row(rid)['status'],'planning_review')
    def test_telegram_editor_hold_feedback_is_authorized_and_version_bound(self):
        from bureau.telegram_app import build_app
        rid=self.seed();self.engine(FakeCreative(rejects=9)).run_one()
        cfg=Config(self.cfg.db,dict(self.cfg.env,TELEGRAM_BOT_TOKEN='123456:OFFLINE_ONLY_012345678901234567890123456789',TELEGRAM_CHAT_ID='22',TELEGRAM_ALLOWED_USER_IDS='11'))
        app=build_app(cfg);callback=next(h.callback for h in app.handlers[0] if h.__class__.__name__=='CallbackQueryHandler')
        update=NS(effective_chat=NS(id=22),effective_user=NS(id=99),update_id=1,callback_query=NS(data=f'creativeedit:{rid}:1',answer=AsyncMock()))
        asyncio.run(callback(update,NS()))
        with self.store.tx() as c:self.assertEqual(c.execute('SELECT count(*) FROM conversations').fetchone()[0],0)
        update.effective_user.id=11;asyncio.run(callback(update,NS()))
        with self.store.tx() as c:self.assertEqual(c.execute('SELECT selection_id FROM conversations').fetchone()[0],rid)

    def test_mock_pipeline_plan_images_bound_approval_and_publication_once(self):
        """Production gates in an isolated DB; every image/network/provider is fake."""
        from test_system import FakeInstagram
        case=deepcopy(CASES[0]);case['candidate']['test_only']=False;case['after']['test_only']=False
        cfg=Config(self.cfg.db,dict(self.cfg.env,IG_ACCOUNT_ID='123',RENDER_DIR=str(self.root/'rendered'),ENABLE_PUBLIC_MEDIA='1',REQUIRE_TOPIC_IMAGE='1'))
        rid=self.seed(case);ai=FakeCreative(case);media=Mock();ig=FakeInstagram();ig.active=True
        files=[];hashes=[]
        import hashlib
        for i in range(5):
            path=self.root/f'page{i}.jpg';data=('fake pixels '+str(i)).encode();path.write_bytes(data);files.append(str(path));hashes.append(hashlib.sha256(data).hexdigest())
        media.render.return_value={'files':files,'urls':[f'https://media.example/page{i}.jpg' for i in range(5)],'sha256':hashes}
        media.expose.return_value={'exposed':True};media.verify.return_value={'verified':True}
        e=Engine(cfg,claude=ai,media=media,telegram=Mock(),instagram=ig);e.run_one()
        self.assertEqual(self.store.row(rid)['status'],'planning_review');self.assertEqual(ig.published,0)
        self.store.accept_draft(rid,1)
        photo={'path':'offline-photo.jpg','sha256':'source-sha','review_required':False,'source_url':'https://example.org/photo','license_url':'https://example.org/license'}
        photos={'content':photo,'resolution_extra':dict(photo,path='offline-photo-2.jpg',sha256='source-sha-2')}
        with patch('bureau.images.select_photos',return_value=photos):e.run_one()
        self.assertEqual(self.store.row(rid)['status'],'preview_ready');self.assertEqual(ig.published,0)
        with self.store.tx() as c:
            payload=json.loads(c.execute("SELECT payload FROM outbox WHERE delivery_key=?",(f'instagram-final:{rid}:1',)).fetchone()[0])
            self.assertEqual(payload['after_delivery'],f'media:{rid}:1')
            self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE kind='publish'").fetchone()[0],0)
            snapshot=c.execute('SELECT * FROM instagram_reviews WHERE selection_id=?',(rid,)).fetchone();short=snapshot['fingerprint'][:16]
        from bureau.publish_review import decide_review
        decide_review(self.store,rid,1,short,True);e.run_one()
        self.assertEqual(ig.published,1);self.assertEqual(self.store.row(rid)['published_id'],'published-media')
        self.assertFalse(e.run_one())
        with self.assertRaises(ValueError):decide_review(self.store,rid,1,short,True)
        with self.store.tx() as c:self.assertEqual(c.execute("SELECT count(*) FROM checkpoints WHERE step='ig_publish'").fetchone()[0],1)
        self.assertEqual([s for s,_ in ai.calls][-1],'image_brief')
    def test_v2_image_revision_clears_snapshot_and_old_buttons_fail(self):
        rid=self.seed();self.engine(FakeCreative()).run_one()
        with self.store.tx() as c:
            c.execute("UPDATE selections SET status='preview_ready' WHERE id=?",(rid,))
            c.execute('INSERT INTO instagram_reviews VALUES(?,?,?,?,1)',(rid,1,'123','old-fingerprint'))
        self.store.await_revision('11',rid,1,'image')
        revision=self.store.apply_revision('11','책상 위 세제 대신 선반에 놓인 세제 사진을 선택해주세요','image-edit:1')
        self.assertEqual(revision,2)
        with self.store.tx() as c:self.assertEqual(c.execute('SELECT approved FROM instagram_reviews WHERE selection_id=?',(rid,)).fetchone()[0],0)
        from bureau.publish_review import decide_review
        with self.assertRaises(ValueError):decide_review(self.store,rid,1,'old-fingerprint',True)
    def test_v2_reader_has_no_unrendered_cover_body(self):
        d=deepcopy(CASES[0]['after']);d['slides'][0]['body']='표지에 표시되지 않을 설명입니다.'
        with self.assertRaises(ValueError):c2.validate_draft(d)
