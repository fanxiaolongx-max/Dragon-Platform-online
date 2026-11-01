import json
import unittest
import httpx
from app import db
from app.config import BETA_QUERY_URL, BETA_SCHEMA, PROD_QUERY_URL, PROD_SCHEMA, settings


class ProfileAdaptationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original = {key: getattr(settings, key) for key in ('BASE_QUERY_URL', 'APP_SCHEMA', 'APP_UUID', 'BUSINESS_DATASOURCE_NAME')}
        self.client, self.gate = db._client, db._gate
        db._gate = db.BaseRequestGate(interval=0)

    async def asyncTearDown(self):
        if db._client is not self.client: await db._client.aclose()
        db._client, db._gate = self.client, self.gate
        for key, value in self.original.items(): setattr(settings, key, value)

    async def test_missing_business_group_adapts_for_http_and_enveloped_errors(self):
        for status in (400, 200):
            sent = []
            settings.BASE_QUERY_URL = 'https://base.fixture/query'
            settings.BUSINESS_DATASOURCE_NAME = 'netcare-retired-group'
            async def handler(request):
                body = json.loads(request.content) if request.content else {}
                sent.append((request.method, body))
                if request.method == 'GET':
                    return httpx.Response(200, json={'code': 0, 'data': [{'name': 'netcareClaw-operate-digital-readonly'}]})
                if body.get('datasourceName') == 'netcare-retired-group':
                    return httpx.Response(status, json={'code': 400, 'message': '数据源不存在: netcare-retired-group'})
                return httpx.Response(200, json={'code': 0, 'data': {'rows': [{'probe': 1}]}})
            db._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            self.assertEqual(await db.query_business('SELECT 1 AS probe', 1), [{'probe': 1}])
            self.assertEqual([method for method, _ in sent], ['POST', 'GET', 'POST'])
            self.assertEqual(sent[-1][1]['datasourceName'], 'netcareClaw-operate-digital-readonly')
            self.assertEqual(sent[-1][1]['sql'], 'SELECT 1 AS probe')
            await db._client.aclose()

    async def test_startup_profile_detection_uses_only_metadata_queries_and_reports_chosen_profile(self):
        settings.BASE_QUERY_URL = BETA_QUERY_URL
        settings.APP_SCHEMA = settings.APP_UUID = BETA_SCHEMA
        sent, observed = [], []
        async def handler(request):
            body = json.loads(request.content)
            sent.append((str(request.url), body))
            rows = [{'TABLE_NAME': 'fixture_table'}] if str(request.url) == PROD_QUERY_URL and body['schema'] == PROD_SCHEMA else []
            return httpx.Response(200, json={'code': 0, 'data': {'rows': rows}})
        db._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        token = db.request_observer.set(lambda response, body, metadata: observed.append(metadata))
        try: await db._ensure_online_profile()
        finally: db.request_observer.reset(token)
        self.assertEqual((settings.BASE_QUERY_URL, settings.APP_SCHEMA, settings.APP_UUID), (PROD_QUERY_URL, PROD_SCHEMA, PROD_SCHEMA))
        self.assertEqual(len(observed), len(sent))
        self.assertTrue(all(body['sql'].startswith('SELECT TABLE_NAME FROM information_schema.TABLES') and body['limit'] == 1 for _, body in sent))
        self.assertTrue(all(item['scope'] == 'app' and item['requestId'] for item in observed))
