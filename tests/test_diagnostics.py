import asyncio
import json
import unittest
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from app import db
from app.config import settings
from app.core.exceptions import DatabaseError, register_exception_handlers
from app.routers import diagnostics
from app.services import database_diagnostics as suite


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_client, self.old_gate = db._client, db._gate
        self.config = {key: getattr(settings, key) for key in ('BASE_QUERY_URL', 'APP_SCHEMA', 'BUSINESS_DATASOURCE_NAME')}
        settings.BASE_QUERY_URL = 'https://base.fixture/query'
        settings.APP_SCHEMA = 'assigned-schema'
        settings.BUSINESS_DATASOURCE_NAME = 'assigned-business'
        self.sent = []
        self.failure = False
        self.catalog = None
        async def handler(request):
            body = json.loads(request.content) if request.content else {}
            self.sent.append((request.method, body))
            if request.method == 'GET' and self.catalog is not None:
                return httpx.Response(200, json={'code': 0, 'data': self.catalog})
            if self.failure:
                return httpx.Response(400, json={'code': 400, 'message': 'SQL rejected token=fixture-secret Bearer abc123', 'data': {'private': 'PRIVATE_RECORD'}, 'detail': [{'loc': ['body', 'sql'], 'msg': 'Unsupported query', 'input': 'PRIVATE_INPUT'}]}, headers={'x-request-id': 'upstream-probe'})
            return httpx.Response(200, json={'code': 0, 'data': {'rows': [{'private': 'PRIVATE_RECORD', 'probe': 1}]}})
        db._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        db._gate = db.BaseRequestGate(interval=0)
        app = FastAPI(); register_exception_handlers(app); app.include_router(diagnostics.router, prefix='/api')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://app.fixture')

    async def asyncTearDown(self):
        await self.client.aclose(); await db._client.aclose()
        db._client, db._gate = self.old_client, self.old_gate
        for key, value in self.config.items(): setattr(settings, key, value)

    async def test_all_default_checks_are_read_only_scoped_and_do_not_export_rows(self):
        manifest = (await self.client.get('/api/diagnostics/database')).json()['data']
        self.assertEqual(len(manifest['checks']), 19)
        for check in manifest['checks']:
            response = await self.client.post('/api/diagnostics/database', json=check)
            result = response.json()['data']
            self.assertEqual(result['status'], 'pass', result)
            self.assertNotIn('PRIVATE_RECORD', json.dumps(result))
            self.assertNotIn('assigned-schema', json.dumps(result))
        for method, body in self.sent:
            self.assertNotIn('execute', str(body))
            if method == 'POST':
                self.assertTrue(body['sql'].upper().startswith('SELECT '))
                self.assertEqual(body['limit'], 1)
                self.assertTrue(body.get('schema') == 'assigned-schema' or body.get('datasourceName') == 'assigned-business')
                self.assertTrue('WHERE 1=0' in body['sql'] or 'information_schema' in body['sql'] or body['sql'] == 'SELECT 1 AS probe')
        self.assertIsNone(db.request_observer.get())

    async def test_http_400_body_is_captured_and_redacted_without_business_records(self):
        self.failure = True
        result = await suite.probe('business-basic')
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['upstream'][0]['httpStatus'], 400)
        self.assertEqual(result['upstream'][0]['requestId'], 'upstream-probe')
        self.assertIn('Unsupported query', result['upstream'][0]['message'])
        for secret in ('fixture-secret', 'abc123', 'PRIVATE_RECORD', 'PRIVATE_INPUT'):
            self.assertNotIn(secret, json.dumps(result))

    async def test_upstream_http_error_preserves_database_error_and_request_metadata(self):
        self.failure = True
        with self.assertRaises(DatabaseError) as caught:
            await db.query_business('SELECT 1 AS probe', 1)
        error = caught.exception
        self.assertEqual(error.code, 500)
        self.assertEqual(error.data['httpStatus'], 400)
        self.assertIn(error.data['requestId'], error.message)
        self.assertNotIn('fixture-secret', error.message)
        self.assertNotIn('PRIVATE_RECORD', json.dumps(error.data))

    async def test_unknown_probes_and_identifier_injection_are_rejected_before_base_call(self):
        for payload in ({'id': 'execute', 'sql': 'DELETE FROM x'}, {'id': 'table-plain', 'table': "x';DROP TABLE y;--"}, {'id': 'app-table:other'}):
            response = await self.client.post('/api/diagnostics/database', json=payload)
            self.assertEqual(response.json()['code'], 400)
        self.assertEqual(self.sent, [])

    async def test_full_scan_only_uses_bounded_static_catalog_and_contexts_are_isolated(self):
        with patch.object(suite, 'catalog', return_value=['known_table']):
            manifest = suite.manifest(full=True)
        self.assertEqual(manifest['checks'][-1]['id'], 'scan-columns')
        self.assertTrue(manifest['coverage']['catalogIsStatic'])
        first, second = await asyncio.gather(suite.probe('app-basic'), suite.probe('business-basic'))
        self.assertEqual(len(first['upstream']), 1); self.assertEqual(len(second['upstream']), 1)
        self.assertNotEqual(first['requestId'], second['requestId'])

    async def test_datasource_mismatch_does_not_guess_or_export_other_groups(self):
        self.catalog = [{'name': 'another-business', 'password': 'HIDDEN_PASSWORD', 'url': 'https://secret@host'}]
        result = await suite.probe('datasources')
        self.assertEqual(result['status'], 'warning')
        self.assertIs(result['datasourceMatch']['configuredNameListed'], False)
        self.assertNotIn('another-business', json.dumps(result))
        self.assertNotIn('HIDDEN_PASSWORD', json.dumps(result))
        self.assertEqual(len(self.sent), 1)
        self.catalog = [{'datasourceName': 'assigned-business'}]
        matched = await suite.probe('datasources')
        self.assertEqual(matched['status'], 'pass')
        self.assertIs(matched['datasourceMatch']['configuredNameListed'], True)

    async def test_process_and_base_request_ids_are_exported_without_payload_or_credentials(self):
        result = await suite.probe('business-basic')
        self.assertEqual(result['runtime']['pid'], __import__('os').getpid())
        request = result['upstream'][0]['request']
        self.assertEqual(request['bootId'], result['runtime']['bootId'])
        self.assertEqual(request['scope'], 'business')
        self.assertEqual(request['businessDatasourceName'], 'assigned-business')
        self.assertEqual(request['method'], 'POST')
        self.assertEqual(request['payloadKeys'], ['datasourceName', 'limit', 'sql'])
        self.assertNotIn('body', request); self.assertNotIn('headers', request)
        self.assertEqual(suite.clean(0), '0')

    async def test_network_failures_keep_scope_and_request_id_without_raw_exception_logging(self):
        await db._client.aclose()
        def fail(request): raise httpx.ConnectError('failed token=fixture-secret', request=request)
        db._client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
        result = await suite.probe('business-basic')
        self.assertEqual(result['status'], 'fail')
        request = result['upstream'][0]['request']
        self.assertEqual(request['networkErrorType'], 'ConnectError')
        self.assertEqual(request['scope'], 'business')
        self.assertIsNone(result['upstream'][0]['httpStatus'])
        self.assertNotIn('fixture-secret', json.dumps(result))


if __name__ == '__main__': unittest.main()
