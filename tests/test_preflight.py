import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch,Mock
from types import SimpleNamespace as NS
from bureau.config import Config
from bureau.adapters import Claude
from bureau.preflight import ConfigurationError,claude_settings,telegram_settings
from bureau.operations import readiness
from bureau.store import Store
from bureau.engine import Engine
import test_system as fixtures

TOKEN='123456:OFFLINE_ONLY_012345678901234567890123456789'


class ProviderPreflightTests(unittest.TestCase):
    def setUp(self):
        self.network=patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN'));self.network.start()
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'test.db'
    def tearDown(self):self.network.stop();self.tmp.cleanup()
    def env(self,**extra):
        return dict({'ENABLE_EXTERNAL_CALLS':'1','CLAUDE_MODEL':'claude-sonnet-5-5','ANTHROPIC_API_KEY':'OFFLINE_KEY_NOT_REAL'},**extra)

    def test_missing_model_stops_before_sdk_construction(self):
        with patch('anthropic.Anthropic') as sdk:
            with self.assertRaises(ConfigurationError) as ctx:Claude(Config(self.db,self.env(CLAUDE_MODEL=''))).generate('test',10)
            self.assertEqual(ctx.exception.code,'claude_model_missing');sdk.assert_not_called()
            self.assertIn('API를 호출하지 않았습니다',str(ctx.exception))

    def test_unknown_model_and_pasted_secret_are_never_echoed(self):
        value='SECRET_PASTED_IN_MODEL_FIELD'
        with patch('anthropic.Anthropic') as sdk:
            with self.assertRaises(ConfigurationError) as ctx:Claude(Config(self.db,self.env(CLAUDE_MODEL=value))).generate('test',10)
            self.assertEqual(ctx.exception.code,'claude_model_unverified');self.assertNotIn(value,str(ctx.exception));sdk.assert_not_called()

    def test_retired_model_cannot_reach_sdk(self):
        with patch('anthropic.Anthropic') as sdk:
            with self.assertRaises(ConfigurationError) as ctx:Claude(Config(self.db,self.env(CLAUDE_MODEL='claude-3-7-sonnet-20250219'))).generate('test',10)
            self.assertEqual(ctx.exception.code,'claude_model_retired');sdk.assert_not_called()

    def test_documented_model_is_not_claimed_account_verified(self):
        result=claude_settings(self.env())
        self.assertTrue(result['model_id_documented']);self.assertFalse(result['account_access_verified'])

    def test_valid_model_reaches_only_mock_sdk_with_retries_disabled(self):
        response=NS(stop_reason='end_turn',content=[NS(type='text',text='{}')],usage=NS(input_tokens=1,output_tokens=2))
        with patch('anthropic.Anthropic') as sdk:
            sdk.return_value.messages.create.return_value=response
            result=Claude(Config(self.db,self.env())).generate('test',10)
            self.assertEqual(result['raw'],'{}');self.assertEqual(sdk.call_args.kwargs['max_retries'],0)
            sdk.return_value.messages.create.assert_called_once()
            self.assertEqual(sdk.return_value.messages.create.call_args.kwargs['model'],'claude-sonnet-5-5')

    def test_configuration_failure_is_not_uncertain_paid_intent(self):
        Store(self.db).migrate();Store(self.db).schedule()
        config=Config(self.db,self.env(CLAUDE_MODEL='',CANDIDATE_GENERATION_MODE='model'))
        engine=Engine(config,claude=Claude(config),media=fixtures.FakeMedia(),telegram=fixtures.FakeTelegram(),instagram=fixtures.FakeInstagram(),news=lambda:fixtures.NEWS)
        with patch('anthropic.Anthropic') as sdk:
            engine.run_one();sdk.assert_not_called()
        with engine.store.tx() as c:
            job=c.execute('SELECT state,error_code FROM jobs').fetchone()
            self.assertEqual(tuple(job),('succeeded',None))
            self.assertEqual(c.execute('SELECT count(*) FROM candidates').fetchone()[0],3)
            self.assertEqual(c.execute("SELECT count(*) FROM checkpoints WHERE step LIKE 'claude%' ").fetchone()[0],0)

    def test_telegram_allowlist_rejects_empty_wildcard_and_names(self):
        env={'TELEGRAM_BOT_TOKEN':TOKEN,'TELEGRAM_CHAT_ID':'-10012345'}
        for users in ('','*','someone','1,,2','0','-3'):
            with self.subTest(users=users),self.assertRaises(ConfigurationError):telegram_settings(dict(env,TELEGRAM_ALLOWED_USER_IDS=users))
        self.assertFalse(telegram_settings(dict(env,TELEGRAM_ALLOWED_USER_IDS='11, 22'))['authentication_verified'])

    def test_bad_telegram_token_never_leaks(self):
        with self.assertRaises(ConfigurationError) as ctx:telegram_settings({'TELEGRAM_BOT_TOKEN':'DO_NOT_ECHO_TOKEN'})
        self.assertNotIn('DO_NOT_ECHO_TOKEN',str(ctx.exception))

    def test_listener_checks_settings_before_builder(self):
        from bureau.telegram_app import build_app
        with patch('telegram.ext.ApplicationBuilder') as builder:
            with self.assertRaises(ConfigurationError):build_app(Config(self.db,{'ENABLE_EXTERNAL_CALLS':'1','TELEGRAM_BOT_TOKEN':TOKEN,'TELEGRAM_CHAT_ID':'1','TELEGRAM_ALLOWED_USER_IDS':'*'}))
            builder.assert_not_called()

    def test_doctor_outputs_codes_without_configuration_values(self):
        secret='SENSITIVE_INVALID_MODEL'
        report=readiness(Config(self.db,self.env(CLAUDE_MODEL=secret,TELEGRAM_BOT_TOKEN='SECRET_TOKEN')))
        encoded=json.dumps(report)
        self.assertNotIn(secret,encoded);self.assertNotIn('SECRET_TOKEN',encoded);self.assertNotIn('OFFLINE_KEY_NOT_REAL',encoded)
        self.assertIn('claude_model_unverified',report['issues'])

    def test_sdk_exception_logs_redact_token_and_traceback(self):
        import logging,io
        from bureau.safe_logging import CredentialFormatter
        output=io.StringIO();handler=logging.StreamHandler(output)
        handler.setFormatter(CredentialFormatter({'TELEGRAM_BOT_TOKEN':TOKEN}))
        logger=logging.Logger('isolated-provider-test');logger.addHandler(handler)
        try:raise ValueError('The token '+TOKEN+' was rejected')
        except ValueError:logger.exception('request token=%s',TOKEN)
        self.assertNotIn(TOKEN,output.getvalue());self.assertIn('[REDACTED]',output.getvalue())

    def test_listener_bootstrap_failure_is_safe_and_not_retried(self):
        from bureau.telegram_app import main
        config=Config(self.db,{'TELEGRAM_BOT_TOKEN':TOKEN})
        with patch('bureau.telegram_app.Config.load',return_value=config),patch('bureau.safe_logging.configure_logging'),patch('bureau.telegram_app.build_app') as app:
            app.return_value.run_polling.side_effect=RuntimeError('The token '+TOKEN+' was rejected')
            with self.assertRaises(SystemExit) as ctx:main()
            self.assertNotIn(TOKEN,str(ctx.exception))
            app.return_value.run_polling.assert_called_once_with(drop_pending_updates=False,bootstrap_retries=0)
