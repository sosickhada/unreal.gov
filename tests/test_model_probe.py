import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,MagicMock,patch
from types import SimpleNamespace as NS
from bureau.config import Config
from bureau.model_probe import plan,probe_once


class ModelProbeTests(unittest.TestCase):
    def setUp(self):
        self.guard=patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN'));self.guard.start()
        self.config=Config(Path('/tmp/unused-model-probe.db'),{'ANTHROPIC_API_KEY':'OFFLINE_ONLY','ENABLE_MODEL_METADATA_LOOKUP':'1'})
    def tearDown(self):self.guard.stop()
    def test_default_plan_does_not_use_sdk(self):
        result=plan('claude-haiku-5-5');self.assertFalse(result['executed']);self.assertEqual(result['generation_requests'],0)
    def test_both_explicit_gates_are_required(self):
        factory=Mock()
        with self.assertRaises(PermissionError):probe_once(self.config,'claude-haiku-5-5',client_factory=factory)
        with self.assertRaises(PermissionError):probe_once(Config(self.config.db,{'ANTHROPIC_API_KEY':'OFFLINE_ONLY'}),'claude-haiku-5-5',approved=True,client_factory=factory)
        factory.assert_not_called()
    def test_only_one_models_get_without_generation(self):
        factory=MagicMock();client=factory.return_value.__enter__.return_value
        client.models.retrieve.return_value=NS(id='claude-haiku-5-5')
        with patch('bureau.safe_logging.configure_logging'):
            result=probe_once(self.config,'claude-haiku-5-5',approved=True,client_factory=factory)
        self.assertTrue(result['account_support_verified']);self.assertEqual(result['metadata_requests'],1)
        client.models.retrieve.assert_called_once_with('claude-haiku-5-5');client.messages.create.assert_not_called()
        self.assertEqual(factory.call_args.kwargs['max_retries'],0);self.assertEqual(factory.call_args.kwargs['base_url'],'https://api.anthropic.com')
    def test_provider_error_is_redacted_without_retry(self):
        factory=MagicMock();client=factory.return_value.__enter__.return_value
        error=RuntimeError('OFFLINE_ONLY secret provider response');error.status_code=404
        client.models.retrieve.side_effect=error
        with patch('bureau.safe_logging.configure_logging'):
            result=probe_once(self.config,'claude-haiku-5-5',approved=True,client_factory=factory)
        self.assertEqual(result['error'],'model_unavailable_or_not_accessible');self.assertEqual(result['metadata_requests'],1)
        self.assertNotIn('OFFLINE_ONLY',str(result));client.models.retrieve.assert_called_once()
    def test_path_injection_or_pasted_secret_is_blocked(self):
        for value in ('claude-x/../../messages','SECRET_TOKEN','claude-a?token=secret'):
            with self.assertRaises(ValueError) as ctx:plan(value)
            self.assertNotIn(value,str(ctx.exception))
