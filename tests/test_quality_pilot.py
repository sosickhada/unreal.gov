from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import unittest
from bureau.config import Config
from bureau.quality_pilot import BudgetedClaude,MAX_CALLS,STAGES,upper_cost,APPROVAL_USD,MODEL,execute,telegram_payloads


class QualityPilotTests(unittest.TestCase):
    def setUp(self):
        self.net=patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN'));self.net.start()
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.cfg=Config(self.root/'unused.db',{'ENABLE_EXTERNAL_CALLS':'1','PAID_AI_CALLS_ENABLED':'1','CLAUDE_MODEL':MODEL,'ANTHROPIC_API_KEY':'offline-key'})
        self.client=Mock();self.client.__enter__=Mock(return_value=self.client);self.client.__exit__=Mock(return_value=False)
        self.client.messages.count_tokens.return_value=NS(input_tokens=1000)
        self.client.messages.create.return_value=NS(stop_reason='end_turn',usage=NS(input_tokens=1000,output_tokens=100),content=[NS(type='text',text='{}')],model=MODEL)
        self.factory=Mock(return_value=self.client)
    def tearDown(self):self.net.stop();self.tmp.cleanup()
    def ai(self,approved=True):return BudgetedClaude(self.cfg,self.root,approved=approved,client_factory=self.factory)
    def test_no_approval_means_no_metadata_count_or_generation(self):
        with self.assertRaises(PermissionError):self.ai(False).generate_role('draft','system','input',4000,model=MODEL)
        with self.assertRaises(PermissionError):execute(self.cfg,self.root,approved=False)
        self.factory.assert_not_called()
    def test_exact_worst_case_budget_and_role_caps(self):
        self.assertEqual(sum(upper_cost(k)*v[0] for k,v in STAGES.items()),Decimal('.0216'))
        self.assertLess(Decimal('.0216'),APPROVAL_USD)
        ai=self.ai()
        for stage,(count,cap) in STAGES.items():
            for _ in range(count):ai.generate_role(stage,'system','input',cap,model=MODEL)
        self.assertEqual(self.client.messages.create.call_count,8)
        self.assertEqual(ai.reserved,Decimal('.0216'))
        with self.assertRaises(ValueError):ai.generate_role('draft','system','input',4000,model=MODEL)
        self.assertEqual(self.client.messages.create.call_count,8)
    def test_large_count_and_forbidden_model_or_stage_never_generate(self):
        ai=self.ai();self.client.messages.count_tokens.return_value=NS(input_tokens=9501)
        with self.assertRaises(ValueError):ai.generate_role('draft','system','input',4000,model=MODEL)
        self.client.messages.create.assert_not_called()
        with self.assertRaises(ValueError):ai.generate_role('ideas','system','input',7000,model=MODEL)
        with self.assertRaises(ValueError):ai.generate_role('draft','system','input',4000,model='claude-sonnet-4-6')
    def test_no_priority_tools_caching_or_retries_and_write_intent_precedes_generation(self):
        def response(**kwargs):
            ledger=json.loads((self.root/'budget.json').read_text());self.assertEqual(ledger['calls'][0]['state'],'sending')
            self.assertEqual(kwargs['service_tier'],'standard_only');self.assertNotIn('tools',kwargs);self.assertNotIn('cache_control',kwargs)
            return NS(stop_reason='end_turn',usage=NS(input_tokens=1000,output_tokens=100),content=[NS(type='text',text='{}')],model=MODEL)
        self.client.messages.create.side_effect=response
        self.ai().generate_role('draft','system','input',4000,model=MODEL)
        self.assertEqual(self.factory.call_args.kwargs['max_retries'],0)
    def test_timeout_remains_uncertain_with_reserved_budget(self):
        from bureau.adapters import ExternalError
        self.client.messages.create.side_effect=TimeoutError('SENSITIVE')
        with self.assertRaises(ExternalError):self.ai().generate_role('draft','system','input',4000,model=MODEL)
        r=json.loads((self.root/'budget.json').read_text());self.assertEqual(r['calls'][0]['state'],'uncertain');self.assertEqual(Decimal(r['reserved_usd']),upper_cost('draft'))
        self.assertEqual(self.client.messages.create.call_count,1)
    def test_telegram_only_comparison_never_contains_approval_callbacks(self):
        cases=json.loads((Path(__file__).parent/'fixtures/creative_v2_cases.json').read_text())['cases']
        baseline=cases[0]['before'];draft=cases[0]['after']
        payloads=telegram_payloads({'raw_claude_baseline':baseline,'published_editorial_baseline':baseline},draft,None,'planning_review')
        self.assertTrue(all('reply_markup' not in p and '게시 금지' in p['text'] for p in payloads))
        self.assertIn('5장',payloads[0]['text']);self.assertIn('고정 브랜드 엔딩',payloads[0]['text'])
