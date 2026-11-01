import asyncio
import json
import unittest
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from app import db
from app.config import settings
from app.core.exceptions import register_exception_handlers
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
        async def handler(request):
            body = json.loads(request.content) if request.content else {}
            self.sent.append((request.method, body))
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


if __name__ == '__main__': unittest.main()
