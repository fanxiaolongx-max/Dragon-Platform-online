"""平台「开放给全员」后按团队隔离月报：官方月报人人可见，团队月报只有本团队和超管可见。"""
import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import time
import unittest
from pathlib import Path

import httpx
from app import db
from app.config import settings
from app.core import identity
from app.core.exceptions import BusinessError, QueryValidationError
from app.services import agent_service, air_service

ROOT = Path(__file__).resolve().parents[1]
ADMIN = identity.Viewer(user='admin', team='default', official=True)
ALICE = identity.Viewer(user='alice', team='alice', official=False)
BOB = identity.Viewer(user='bob', team='bob', official=False)


def doc(name, month='2026-09', **extra):
    return {'name': name, 'reportMonth': month, 'template': {}, 'style': {'prompt': ''},
            'chapters': [{'id': 'chapter-1', 'title': {'zh': '总览'}, 'cells': [{'id': 'cell-1', 'span': 6, 'prompt': 'p'}]}], **extra}


class TeamIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connection = sqlite3.connect(':memory:', isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript((ROOT / 'db/init.sqlite.sql').read_text())
        self.saved = {key: getattr(settings, key) for key in ('BASE_QUERY_URL', 'APP_DATASOURCE_ID', 'APP_SCHEMA', 'BUSINESS_DATASOURCE_NAME')}
        settings.BASE_QUERY_URL, settings.APP_DATASOURCE_ID = 'https://base.fixture/dh/query', 'app'
        settings.APP_SCHEMA, settings.BUSINESS_DATASOURCE_NAME = 'fixture-schema', 'fixture-business'
        self.state = (db._gate, air_service._save_lock, db._client, db._dialect_checked)
        db._gate, air_service._save_lock, db._dialect_checked = db.BaseRequestGate(), asyncio.Lock(), False
        db._client = httpx.AsyncClient(transport=httpx.MockTransport(self.handle), trust_env=False)
        self.token = identity.set_current(None)

    async def asyncTearDown(self):
        identity.reset(self.token)
        await db._client.aclose()
        db._gate, air_service._save_lock, db._client, db._dialect_checked = self.state
        for key, value in self.saved.items():
            setattr(settings, key, value)
        self.connection.close()

    def handle(self, request):
        body = json.loads(request.content)
        if 'datasourceName' in body:
            return httpx.Response(200, json={'code': 0, 'data': {'rows': [{'total': 1}]}})
        try:
            if request.url.path == '/dh/execute':
                return httpx.Response(200, json={'code': 0, 'data': {'affectedRows': self.connection.execute(body['sql']).rowcount}})
            rows = [dict(row) for row in self.connection.execute(body['sql']).fetchmany(body['limit'])]
            return httpx.Response(200, json={'code': 0, 'data': {'rows': rows}})
        except sqlite3.Error as error:
            return httpx.Response(200, json={'code': 500, 'message': str(error), 'data': None})

    def act(self, viewer):
        identity.reset(self.token)
        self.token = identity.set_current(viewer)

    async def names(self):
        return sorted(entry['name'] for entry in await air_service.list_documents())

    async def test_official_reports_are_shared_and_team_reports_stay_private(self):
        legacy = await air_service.save_document(doc('旧月报', '2026-07'))  # 没有身份头时保存：算官方月报
        self.act(ADMIN)
        official = await air_service.save_document(doc('官方月报'))
        self.assertEqual(official['owner'], {'official': True, 'team': '', 'user': 'admin', 'mine': True, 'editable': True})

        self.act(ALICE)
        self.assertEqual(await self.names(), ['官方月报', '旧月报'])
        shown = await air_service.read_document(official['id'])
        self.assertEqual((shown['owner']['official'], shown['owner']['editable']), (True, False))
        # 团队成员改不了、删不了官方月报，也不能借页面提交的 owner 冒充
        for change in (lambda: air_service.save_document({**shown, 'name': '被改了', 'owner': {'official': False, 'team': 'alice'}}),
                       lambda: air_service.delete_document(official['id']),
                       lambda: air_service.upsert_cell(official['id'], 'cell-1', None, '改提示词'),
                       lambda: air_service.delete_cell(official['id'], 'cell-1'),
                       lambda: air_service.set_style_prompt(official['id'], 'x'),
                       lambda: air_service.delete_document(legacy['id'])):
            with self.assertRaises(BusinessError) as raised:
                await change()
            self.assertEqual(raised.exception.code, 403)
        # 同一个月已有官方月报，团队仍可以有自己的当月月报
        mine = await air_service.save_document(doc('Alice 月报'))
        self.assertEqual(mine['owner'], {'official': False, 'team': 'alice', 'user': 'alice', 'mine': True, 'editable': True})
        copy = await air_service.save_document({**shown, 'id': '', 'name': '官方月报副本', 'reportKind': 'copy', 'saveAs': True, 'saveKey': 'save-alice-1'})
        self.assertEqual(copy['owner']['team'], 'alice')
        listed = await air_service.list_documents()
        self.assertEqual(listed[0]['name'], 'Alice 月报', 'own default report comes before the official one')
        self.assertEqual({entry['name']: entry['isDefault'] for entry in listed},
                         {'Alice 月报': True, '官方月报': True, '旧月报': True, '官方月报副本': False})
        await air_service.upsert_cell(mine['id'], 'cell-1', None, '新的提示词')

        self.act(BOB)
        self.assertEqual(await self.names(), ['官方月报', '旧月报'])
        for hidden in (lambda: air_service.read_document(mine['id']), lambda: air_service.delete_document(mine['id']),
                       lambda: air_service.save_document({**mine, 'name': 'Bob 抢改'}),
                       lambda: air_service.save_document({**doc('撞标识'), 'saveKey': 'save-alice-1', 'saveAs': True}),
                       lambda: air_service.upsert_cell(mine['id'], 'cell-1', None, 'x')):
            with self.assertRaises(BusinessError):
                await hidden()
        self.assertEqual((await agent_service.execute('report_outline', {}))['result']['reports'].__len__(), 2)

        self.act(ADMIN)
        self.assertEqual(await self.names(), ['Alice 月报', '官方月报', '官方月报副本', '旧月报'])
        seen = next(entry for entry in await air_service.list_documents() if entry['name'] == 'Alice 月报')
        self.assertEqual((seen['owner']['official'], seen['owner']['team'], seen['owner']['mine'], seen['owner']['editable']), (False, 'alice', False, True))
        renamed = await air_service.save_document({**(await air_service.read_document(mine['id'])), 'name': 'Alice 月报（超管修订）'})
        self.assertEqual(renamed['owner']['team'], 'alice', 'editing by the super admin keeps the team ownership')

    async def test_members_cannot_reach_other_teams_through_raw_app_schema_access(self):
        self.act(ALICE)
        denied = [
            lambda: agent_service.execute('query', {'source': 'app', 'sql': 'SELECT * FROM t_report_template'}),
            lambda: agent_service.execute('update_row', {'table': 't_report_template', 'id': 1, 'values': {'name': 'x'}}),
            lambda: agent_service.execute('delete_row', {'table': 't_report_block', 'id': 1}),
            lambda: agent_service.execute('insert_row', {'table': 't_report_config', 'values': {'report_id': 1}}),
        ]
        for call in denied:
            with self.assertRaises(BusinessError) as raised:
                await call()
            self.assertEqual(raised.exception.code, 403)
        ran = await air_service.run_data('2026-09', {'sources': [
            {'id': 'a', 'kind': 'sql', 'source': 'app', 'sql': 'SELECT name FROM t_report_template'},
            {'id': 'b', 'kind': 'sql', 'source': 'netcare', 'sql': 'SELECT COUNT(*) AS total FROM t_any'}]})
        self.assertIsNone(ran['input']['a'])
        self.assertEqual(ran['input']['b']['rows'], [{'total': 1}])
        self.assertEqual((await agent_service.execute('query', {'source': 'netcare', 'sql': 'SELECT 1 AS total'}))['status'], 'ok')
        for method, path, blocked in (('GET', '/api/reports', True), ('POST', '/api/reports/3/blocks', True), ('GET', '/api/ops/logs', True),
                                      ('POST', '/api/ops/logs', False), ('GET', '/dev', True), ('GET', '/docs', True), ('POST', '/api/ai-models/select', True),
                                      ('GET', '/api/ai-models', False), ('POST', '/api/ai-models/generate', False), ('DELETE', '/api/data-sources/1', True),
                                      ('GET', '/api/air/documents', False), ('POST', '/api/air/documents', False), ('POST', '/api/agent/execute', False)):
            self.assertEqual(identity.member_blocked(method, path), blocked, f'{method} {path}')

    def test_identity_headers_must_carry_a_valid_team_signature(self):
        os.environ['PLATFORM_APP_SECRET'] = 'unit-secret'
        self.addCleanup(os.environ.pop, 'PLATFORM_APP_SECRET', None)

        def headers(team, tenant='default', user='alice', role='readonly', stamp=None, secret='unit-secret'):
            stamp = str(int(time.time() * 1000)) if stamp is None else stamp
            signature = hmac.new(secret.encode(), f'{user}\n{role}\n{tenant}\n{team}\n{stamp}'.encode(), hashlib.sha256).hexdigest()
            return {'x-platform-user': user, 'x-platform-role': role, 'x-platform-tenant': tenant, 'x-platform-user-tenant': team,
                    'x-platform-timestamp': stamp, 'x-platform-team-signature': signature}

        self.assertIsNone(identity.from_headers({'x-platform-user': 'someone'}), 'no team header: base deployment, no isolation')
        self.assertEqual(identity.from_headers(headers('alice')), ALICE)
        self.assertEqual(identity.from_headers(headers('default', user='admin', role='admin')), ADMIN)
        forged = {**headers('alice'), 'x-platform-user-tenant': 'default'}
        for bad in (forged, headers('alice', secret='wrong'), headers('alice', stamp=str(int(time.time() * 1000) - 3600_000)), headers('')):
            with self.assertRaises(identity.IdentityError):
                identity.from_headers(bad)


if __name__ == '__main__':
    unittest.main()
