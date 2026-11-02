"""Model contracts, encrypted persistence, migration, and cancellation. No paid model calls."""
import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet

from app import db
from app.config import settings
from app.core.exceptions import BusinessError
from app.routers.ai_models import Generate, connected
from app.services import ai_models as service
from app.utils.sql_contract import assert_app_write, assert_read_query

ROOT = Path(__file__).resolve().parents[1]


class ModelsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connection = sqlite3.connect(':memory:', isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript((ROOT / 'db/init.sqlite.sql').read_text())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patches = [patch.object(settings, 'AI_MODEL_ENCRYPTION_KEY', ''),
                        patch.object(settings, 'AI_MODEL_KEY_FILE', str(Path(self.tmp.name) / 'models.key')),
                        patch.object(service, '_lock', asyncio.Lock()),
                        patch.object(db, 'query_app_schema', self.query), patch.object(db, 'execute_app_schema', self.execute)]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        self.sqls = []
        self.profile = {'name': '内网模型', 'protocol': 'openai', 'base_url': 'http://model.fixture:11434/v1', 'model': 'test-model',
                        'api_key': 'fixture-private-key', 'headers': {'X-Private': 'fixture-private-header'}}

    async def asyncTearDown(self): self.connection.close()

    async def query(self, sql, limit=100):
        assert_read_query(sql)
        self.sqls.append(sql)
        return [dict(r) for r in self.connection.execute(sql).fetchmany(limit)]

    async def execute(self, sql):
        assert_app_write(sql)
        self.sqls.append(sql)
        return self.connection.execute(sql).rowcount

    async def test_encrypted_save_read_update_delete_and_selection(self):
        saved = await service.save(self.profile)
        self.assertTrue(saved['has_api_key'])
        stored = self.connection.execute('SELECT * FROM t_ai_model_config').fetchone()
        self.assertNotIn('fixture-private-key', str(tuple(stored)))
        self.assertNotIn('fixture-private-header', '\n'.join(self.sqls))
        self.assertNotIn('内网模型', str(tuple(stored)), 'Entire configuration is encrypted')
        keyfile = Path(settings.AI_MODEL_KEY_FILE)
        self.assertEqual(keyfile.stat().st_mode & 0o777, 0o600)
        self.assertNotEqual(keyfile.read_text(), stored['config_cipher'])
        await service.select('model', saved['id'])
        listed = await service.listing()
        self.assertEqual(listed['config_id'], saved['id'])
        self.assertEqual(listed['items'][0]['name'], '内网模型')
        self.assertNotIn('api_key', listed['items'][0])
        self.assertNotIn('headers', listed['items'][0])
        self.assertNotIn('config_cipher', str(listed))
        original = await service.row_for(saved['id'])
        updated = await service.save({**saved, 'name': 'renamed', 'api_key': '', 'headers': ''})
        self.assertEqual(service.decode(await service.row_for(saved['id']))['api_key'], self.profile['api_key'])
        with self.assertRaisesRegex(BusinessError, '其他页面'): await service.save({**saved, 'name': 'stale'})
        with self.assertRaisesRegex(BusinessError, '先切换'): await service.remove(saved['id'])
        cleared = await service.save({**updated, 'clear_api_key': True, 'headers': {}})
        self.assertFalse(cleared['has_api_key'])
        self.assertFalse(cleared['has_headers'])
        self.assertNotEqual(original['revision'], cleared['revision'])
        await service.select('adc')
        await service.remove(saved['id'])
        self.assertEqual((await service.listing())['items'], [])

    async def test_wrong_key_is_not_silently_overwritten_and_tampering_is_rejected(self):
        saved = await service.save(self.profile)
        with patch.object(settings, 'AI_MODEL_ENCRYPTION_KEY', Fernet.generate_key().decode()):
            self.assertTrue((await service.listing())['items'][0]['locked'])
            with self.assertRaisesRegex(BusinessError, '恢复原加密'): await service.save({**saved, 'name': 'bad'})
        row = await service.row_for(saved['id'])
        row['config_cipher'] = row['config_cipher'][:-7] + 'changed'
        with self.assertRaises(BusinessError): service.decode(row)
        self.assertEqual(service.decode(await service.row_for(saved['id']))['api_key'], self.profile['api_key'])

    async def test_private_key_survives_service_reload(self):
        saved = await service.save(self.profile)
        first = Path(settings.AI_MODEL_KEY_FILE).read_bytes()
        self.assertEqual(service.decode(await service.row_for(saved['id']))['model'], 'test-model')
        self.assertEqual(Path(settings.AI_MODEL_KEY_FILE).read_bytes(), first)

    async def test_invalid_addresses_headers_and_protocols_never_send(self):
        for url in ('file:///etc/passwd', 'ftp://a/b', 'https://user:password@host/v1', 'http://host?api_key=key', 'http://host#key', 'http://host:bad', 'http://host/\r\nsecret'):
            with self.subTest(url=url), self.assertRaises(BusinessError): service.validate({**self.profile, 'base_url': url})
        for headers in ({'Host': 'other'}, {'Cookie': 'secret'}, {'X-Something': 'a\nb'}):
            with self.assertRaises(BusinessError): service.validate({**self.profile, 'headers': headers})
        for auth in ('Host', 'Cookie', 'Content-Length'):
            with self.assertRaises(BusinessError): service.validate({**self.profile, 'auth_type': 'custom', 'auth_header': auth})
        self.assertEqual(service.validate({**self.profile, 'base_url': 'http://10.0.0.5:8000/v1'})['base_url'], 'http://10.0.0.5:8000/v1')

    async def test_all_protocols_send_expected_payload_and_read_only_text(self):
        fixtures = {
            'openai': ('/v1/chat/completions', {'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}]}),
            'responses': ('/v1/responses', {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'OK'}]}]}),
            'anthropic': ('/v1/messages', {'content': [{'type': 'thinking', 'thinking': 'private reasoning'}, {'type': 'text', 'text': 'OK'}]}),
            'gemini': ('/v1/models/test-model:generateContent', {'candidates': [{'content': {'parts': [{'thought': True, 'text': 'private reasoning'}, {'text': 'OK'}]}}]}),
            'ollama': ('/v1/api/chat', {'message': {'content': 'OK'}}),
            'custom': ('/v1', {'data': {'answer': 'OK'}}),
        }
        real_client = httpx.AsyncClient
        seen = []
        for protocol, (path, reply) in fixtures.items():
            with self.subTest(protocol=protocol):
                def handle(request):
                    seen.append(request)
                    self.assertEqual(request.url.scheme, 'http')
                    self.assertEqual(request.url.path, path)
                    self.assertNotIn('cookie', request.headers)
                    self.assertNotIn('x-app-id', request.headers)
                    body = json.loads(request.content)
                    if protocol not in ('gemini', 'custom'): self.assertIs(body['stream'], False)
                    if protocol == 'anthropic':
                        self.assertEqual(request.headers['x-api-key'], self.profile['api_key'])
                        self.assertEqual(body['system'], 'system')
                    if protocol == 'gemini':
                        self.assertEqual(request.headers['x-goog-api-key'], self.profile['api_key'])
                        self.assertEqual(body['contents'][1]['role'], 'model')
                    if protocol == 'responses': self.assertFalse(body['store'])
                    if protocol == 'custom':
                        self.assertEqual(body['history'][0]['role'], 'system')
                        self.assertIsInstance(body['tokens'], int)
                        self.assertEqual(body['question'], 'final')
                    return httpx.Response(200, json=reply)
                def factory(**kw):
                    self.assertFalse(kw['trust_env'])
                    self.assertFalse(kw['follow_redirects'])
                    return real_client(transport=httpx.MockTransport(handle), **kw)
                c = service.validate({**self.profile, 'protocol': protocol, 'body_template': {'history': '${messages}', 'question': '${prompt}', 'tokens': '${max_tokens}'}, 'response_path': 'data.answer'})
                with patch('app.services.ai_models.httpx.AsyncClient', side_effect=factory):
                    result = await service.invoke(c, [{'role': 'user', 'content': 'first'}, {'role': 'assistant', 'content': 'reply'}, {'role': 'user', 'content': 'final'}], 'system')
                self.assertEqual(result['text'], 'OK')
        self.assertEqual(len(seen), 6)

    async def test_full_urls_query_parameters_advanced_parameters_and_no_external_tools(self):
        for protocol, url in [('openai', 'https://host/v1/chat/completions?api-version=1'), ('responses', 'https://host/v1/responses'), ('anthropic', 'http://host/v1/messages'), ('gemini', 'https://host/v1beta/models/test-model:generateContent'), ('ollama', 'http://host/api/chat')]:
            c = service.validate({**self.profile, 'protocol': protocol, 'base_url': url})
            target, _, _ = service.wire(c, [{'role': 'user', 'content': 'test'}])
            self.assertEqual(target, url)
        c = service.validate({**self.profile, 'base_url': 'https://host', 'extra_body': {'temperature': None, 'max_tokens': None, 'max_completion_tokens': 4000}})
        target, _, body = service.wire(c, [{'role': 'user', 'content': 'test'}])
        self.assertEqual(target, 'https://host/v1/chat/completions')
        self.assertNotIn('temperature', body)
        self.assertNotIn('max_tokens', body)
        self.assertEqual(body['max_completion_tokens'], 4000)
        c['extra_body']['tools'] = [{'type': 'web_search'}]
        with self.assertRaisesRegex(BusinessError, '外部工具'): service.wire(c, [{'role': 'user', 'content': 'test'}])

    async def test_test_model_uses_draft_without_saving_and_errors_never_echo_secrets(self):
        real_client = httpx.AsyncClient
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(401, json={'error': {'message': self.profile['api_key']}})
        with patch('app.services.ai_models.httpx.AsyncClient', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)):
            with self.assertRaises(BusinessError) as error: await service.test_model(self.profile)
        self.assertEqual(error.exception.code, 401)
        self.assertNotIn(self.profile['api_key'], str(error.exception))
        self.assertEqual(len(calls), 1, 'No automatic retries on model calls')
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM t_ai_model_config').fetchone()[0], 0)

    async def test_configuration_revision_blocks_late_model_calls(self):
        saved = await service.save(self.profile)
        await service.save({**saved, 'model': 'new-model'})
        body = Generate(config_id=saved['id'], revision=saved['revision'], messages=[{'role': 'user', 'content': 'hi'}])
        with self.assertRaisesRegex(BusinessError, '本次操作已停止'): await service.generate(body)

    async def test_disconnect_cancels_pending_upstream_operation(self):
        cancelled = asyncio.Event()
        class Request:
            async def is_disconnected(self): return True
        async def operation():
            try: await asyncio.sleep(20)
            finally: cancelled.set()
        with self.assertRaises(BusinessError) as error: await connected(Request(), operation())
        self.assertEqual(error.exception.code, 499)
        self.assertTrue(cancelled.is_set())

    async def test_migration_idempotence_and_existing_report_preservation(self):
        self.connection.execute("INSERT INTO t_report_template(name,title) VALUES('existing','keep me')")
        for _ in range(2): self.connection.executescript((ROOT / 'db/upgrade.sqlite.sql').read_text())
        self.assertEqual(self.connection.execute('SELECT title FROM t_report_template').fetchone()[0], 'keep me')
        saved = await service.save(self.profile)
        self.connection.executescript((ROOT / 'db/upgrade.sqlite.sql').read_text())
        self.assertEqual(service.decode(await service.row_for(saved['id']))['api_key'], self.profile['api_key'])
