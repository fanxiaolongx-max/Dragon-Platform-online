"""Interaction log, table failure tags and business table snapshot, through a fake base REST API."""
import asyncio
import json
import sqlite3
import unittest
from pathlib import Path

import httpx
from app import db
from app.config import settings
from app.core.exceptions import DatabaseError
from app.routers import table_map
from app.services import agent_service, ops_service
from app.utils.sql_contract import assert_app_write

ROOT = Path(__file__).resolve().parents[1]


class OpsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connection = sqlite3.connect(':memory:', isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript((ROOT / 'db/init.sqlite.sql').read_text())
        self.tables = [('risk_task_new', '风险任务'), ('op_ioc_rectify_check_d_dwd', '整改明细')]
        self.status = {}
        self.original_settings = {key: getattr(settings, key) for key in ('BASE_QUERY_URL', 'APP_DATASOURCE_ID', 'APP_SCHEMA', 'BUSINESS_DATASOURCE_NAME')}
        settings.BASE_QUERY_URL = 'https://base.fixture/dh/query'
        settings.APP_DATASOURCE_ID = 'app'
        settings.APP_SCHEMA = 'fixture-schema'
        settings.BUSINESS_DATASOURCE_NAME = 'fixture-business'
        self.original_gate, self.original_client = db._gate, db._client
        db._gate = db.BaseRequestGate(interval=0)
        db._client = httpx.AsyncClient(transport=httpx.MockTransport(self.handle), trust_env=False)
        self.original_listeners = list(db.request_listeners)
        ops_service.FLUSH_DELAY = 0
        for name, value in dict(_buffer=[], _flush_task=None, _last_prune=0.0, _health={}, _health_touched={}, _health_loaded=False,
                                _health_dirty=False, _snapshot=None, _snapshot_checked=0.0, _refresh_lock=asyncio.Lock()).items():
            setattr(ops_service, name, value)
        ops_service.install()

    async def asyncTearDown(self):
        db.request_listeners[:] = self.original_listeners
        await db._client.aclose()
        db._gate, db._client = self.original_gate, self.original_client
        for key, value in self.original_settings.items():
            setattr(settings, key, value)
        self.connection.close()

    def handle(self, request):
        body = json.loads(request.content)
        sql = body['sql']
        if 'datasourceName' in body:
            if 'information_schema.COLUMNS' in sql:
                return httpx.Response(200, json={'code': 0, 'data': {'rows': [
                    {'COLUMN_NAME': 'region_name_cn', 'DATA_TYPE': 'varchar', 'COLUMN_COMMENT': '地区部'},
                    {'COLUMN_NAME': 'rep_office_name_cn', 'DATA_TYPE': 'varchar', 'COLUMN_COMMENT': '代表处'},
                    {'COLUMN_NAME': 'cnt', 'DATA_TYPE': 'int', 'COLUMN_COMMENT': ''}]}})
            if 'UNION ALL' in sql:
                self.union_sql = sql
                return httpx.Response(200, json={'code': 0, 'data': {'rows': [{'col': 'rep_office_name_cn', 'val': '埃及代表处', 'n': 12}]}})
            if 'information_schema.TABLES' in sql:
                return httpx.Response(200, json={'code': 0, 'data': {'rows': [{'TABLE_NAME': t, 'TABLE_COMMENT': c} for t, c in self.tables]}})
            for table, status in self.status.items():
                if table in sql and status:
                    return httpx.Response(status, json={'code': status, 'message': f'{table} 执行失败'})
            return httpx.Response(200, json={'code': 0, 'data': {'rows': [{'n': 1}]}})
        try:
            if request.url.path == '/dh/execute':
                assert_app_write(sql)
                return httpx.Response(200, json={'code': 0, 'data': {'affectedRows': self.connection.execute(sql).rowcount}})
            return httpx.Response(200, json={'code': 0, 'data': {'rows': [dict(r) for r in self.connection.execute(sql).fetchmany(body['limit'])]}})
        except sqlite3.Error as error:
            return httpx.Response(200, json={'code': 500, 'message': str(error)})

    def stored(self, section):
        return [json.loads(r['config_text']) for r in self.connection.execute(
            'SELECT config_text FROM t_report_config WHERE report_id = 0 AND section = ? ORDER BY id', (section,))]

    async def test_failed_query_is_logged_tags_the_table_and_a_later_success_clears_it(self):
        self.status['bad_tbl'] = 500
        for _ in range(2):
            with self.assertRaises(DatabaseError):
                await db.query_business('SELECT * FROM `bad_tbl` LIMIT 10')
        await db.query_business('SELECT * FROM risk_task_new')
        await ops_service.flush()
        health = self.stored('ops_tbl_health')[-1]
        self.assertEqual(health['bad_tbl']['fails'], 2)
        self.assertIn('bad_tbl 执行失败', health['bad_tbl']['lastError'])
        self.assertNotIn('risk_task_new', health)
        logs = (await ops_service.list_logs(limit=50, kind='db', status='error'))['logs']
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0]['detail']['tables'], ['bad_tbl'])
        self.assertEqual(logs[0]['detail']['httpStatus'], 500)
        self.assertTrue(logs[0]['detail']['requestId'])
        self.assertEqual(logs[0]['title'], '业务库查询 · bad_tbl 失败')
        # The log's own reads and writes are never logged.
        self.assertFalse(any('ops_log' in json.dumps(e, ensure_ascii=False) for e in self.stored('ops_log')))

        self.status['bad_tbl'] = 0
        await db.query_business('SELECT COUNT(*) AS n FROM bad_tbl')
        self.assertEqual(await ops_service.table_health(), {})
        await ops_service.flush()
        self.assertEqual(self.stored('ops_tbl_health')[-1], {})

    async def test_platform_wide_failures_do_not_tag_tables(self):
        for status in (429, 503):
            self.status = {'risk_task_new': status}
            with self.assertRaises(DatabaseError):
                await db.query_business('SELECT * FROM risk_task_new')
        self.assertEqual(await ops_service.table_health(), {})
        self.assertEqual(ops_service.tables_in('WITH a AS (SELECT * FROM x JOIN netcare.`y` ON 1) SELECT * FROM a, information_schema.TABLES'), ['x', 'y'])

    async def test_table_list_refresh_reports_added_and_removed_tables(self):
        first = await ops_service.refresh_tables('air')
        self.assertTrue(first['first'])
        self.assertEqual(first['total'], 2)
        self.assertTrue((await ops_service.refresh_tables('dev'))['reused'], 'A second page opening within a minute reuses the result')
        self.tables = [('risk_task_new', '风险任务'), ('brand_new_tbl', '新表'), ('another_new', '')]
        second = await ops_service.refresh_tables('dev', force=True)
        self.assertEqual([t['t'] for t in second['added']], ['brand_new_tbl', 'another_new'])
        self.assertEqual([t['t'] for t in second['removed']], ['op_ioc_rectify_check_d_dwd'])
        logs = (await ops_service.list_logs(kind='tables'))['logs']
        self.assertEqual(logs[0]['title'], '业务表清单刷新：共 3 张（上次 2 张），新增 2 张，减少 1 张')
        self.assertEqual(logs[0]['page'], 'dev')
        self.assertEqual(logs[1]['title'], '业务表清单首次记录：共 2 张表')
        self.assertEqual(self.stored('ops_tbl_snap')[-1]['total'], 3)

        # A table that only exists in the latest list can be queried directly.
        ops_service._snapshot = None
        lookup = await table_map.lookup_table('brand_new_tbl')
        self.assertEqual(lookup['data']['resolved_table'], 'brand_new_tbl')
        data = await table_map.query_by_table('brand_new_tbl', 10, [], '')
        self.assertEqual(data['code'], 0)
        missing = await table_map.query_by_table('nowhere_tbl', 10, [], '')
        self.assertEqual(missing['code'], 404)
        self.assertEqual((await ops_service.list_logs(kind='api', status='error'))['logs'][0]['detail'], {'table': 'nowhere_tbl'})

    async def test_ai_table_list_puts_failed_tables_last(self):
        self.status['op_ioc_rectify_check_d_dwd'] = 500
        with self.assertRaises(DatabaseError):
            await db.query_business('SELECT * FROM op_ioc_rectify_check_d_dwd')
        result = await agent_service._list_tables({'source': 'netcare'})
        self.assertEqual(result['rows'][-1]['table'], 'op_ioc_rectify_check_d_dwd')
        self.assertEqual(result['rows'][-1]['failed'], 1)
        self.assertNotIn('failed', result['rows'][0])

    async def test_browser_reports_adc_conversations(self):
        accepted = ops_service.record_client([{'kind': 'adc', 'status': 'error', 'title': 'ADC 对话失败', 'ms': 1200,
                                               'detail': {'prompt': 'x' * 9000, 'error': '流提前结束'}}, 'not an entry'], 'air')
        self.assertEqual(accepted, 1)
        log = (await ops_service.list_logs(kind='adc'))['logs'][0]
        self.assertEqual((log['page'], log['status'], log['ms']), ('air', 'error', 1200))
        self.assertLess(len(log['detail']['prompt']), 4100)
        self.assertEqual(log['detail']['error'], '流提前结束')
        self.assertEqual((await ops_service.list_logs(q='流提前结束'))['logs'][0]['id'], log['id'])
        self.assertEqual((await ops_service.list_logs(q='不存在的关键字'))['logs'], [])

    async def test_routes_record_the_calling_page(self):
        from app.main import create_app
        app = create_app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://app.fixture') as client:
            response = await client.get('/api/data/table-map/data', params={'name': 'risk_task_new', 'limit': 5},
                                        headers={'X-Ops-Page': 'dev'})
            self.assertEqual(response.json()['code'], 0)
            posted = await client.post('/api/ops/logs', json={'entries': [{'kind': 'adc', 'title': 'ADC 对话 · AI 月报'}]},
                                       headers={'Referer': 'http://app.fixture/digital-human/app/'})
            self.assertEqual(posted.json()['data'], {'accepted': 1})
            refreshed = (await client.post('/api/ops/tables/refresh', json={}, headers={'X-Ops-Page': 'air'})).json()['data']
            self.assertEqual(refreshed['total'], 2)
            logs = (await client.get('/api/ops/logs', params={'limit': 20})).json()['data']['logs']
        by_kind = {log['kind']: log for log in reversed(logs)}
        # risk_task_new is an upstream source table; 源表直查 queries its landing table instead.
        query = next(log for log in logs if log['kind'] == 'db' and 'op_ioc_risk_task_d_dwd' in log['detail'].get('tables', []))
        self.assertEqual((query['page'], query['route']), ('dev', '/api/data/table-map/data'))
        self.assertEqual(next(log for log in logs if log['kind'] == 'db' and 'information_schema' in log['detail']['sql'])['page'], 'air')
        self.assertEqual(by_kind['adc']['page'], 'air')
        self.assertEqual((by_kind['tables']['page'], by_kind['tables']['title']), ('air', '业务表清单首次记录：共 2 张表'))

    async def test_suggest_tables_and_find_value_save_model_round_trips(self):
        self.tables = [('nc_eos_risk_product_version_dws', 'EOS风险产品版本统计'), ('op_ioc_rectify_check_d_dwd', '整改明细'), ('nc_eos_other', 'EOS 其他')]
        suggested = (await agent_service.execute('suggest_tables', {'text': '埃及代表处 EOS 风险产品版本每月统计'}))['result']
        self.assertEqual([t['table'] for t in suggested['tables']], ['nc_eos_risk_product_version_dws', 'nc_eos_other'])
        self.assertIn('风险', suggested['tables'][0]['matched'])
        self.assertEqual(suggested['columns'][0]['table'], 'nc_eos_risk_product_version_dws')
        self.assertEqual(len(suggested['columns']), 1, 'a much weaker second match gets no column lookup')
        named = (await agent_service.execute('suggest_tables', {'text': '数据来源 op_ioc_rectify_check_d_dwd，按月'}))['result']
        self.assertEqual(named['tables'][0]['table'], 'op_ioc_rectify_check_d_dwd')
        self.assertEqual((await agent_service.execute('suggest_tables', {'text': '你好'}))['result']['tables'], [])

        found = (await agent_service.execute('find_value', {'source': 'netcare', 'table': 'nc_eos_risk_product_version_dws', 'keyword': "埃及'; DROP"}))['result']
        self.assertEqual(found['matches'], [{'column': 'rep_office_name_cn', 'value': '埃及代表处', 'rows': 12}])
        self.assertEqual(found['searched_columns'], ['region_name_cn', 'rep_office_name_cn'], 'only text columns are searched')
        self.assertIn("LIKE '%埃及 DROP%'", self.union_sql)
        with self.assertRaises(Exception):
            await agent_service.execute('find_value', {'source': 'netcare', 'table': 'nc_eos_risk_product_version_dws', 'keyword': '埃及', 'columns': ['cnt']})

    async def test_client_kinds_time_and_a_bad_row_does_not_drop_its_batch(self):
        accepted = ops_service.record_client([
            {'kind': 'model', 'title': '模型 API 对话', 'clientAt': '2020-01-01T00:00:00Z'},
            {'kind': 'ai', 'title': 'AI 月报 · 格子对话', 'detail': {'rounds': 3}},
            {'kind': 'weird', 'title': 'BAD row'}], 'air')
        self.assertEqual(accepted, 3)
        original = db.execute_app_schema

        async def picky(sql):
            if 'BAD row' in sql:
                raise db.DatabaseError('Incorrect string value')
            return await original(sql)
        ops_service.db.execute_app_schema = picky
        try:
            await ops_service.flush()
        finally:
            ops_service.db.execute_app_schema = original
        stored = self.stored('ops_log')
        self.assertEqual([e['kind'] for e in stored], ['model', 'ai'])
        self.assertNotEqual(stored[0]['at'][:4], '2020', 'implausible browser times fall back to the server time')

    async def test_missing_table_skips_per_row_retry(self):
        ops_service.record_client([
            {'kind': 'ui', 'title': 'A'},
            {'kind': 'ui', 'title': 'B'},
            {'kind': 'ui', 'title': 'C'}], 'air')
        calls = []
        original = db.execute_app_schema

        async def fail_missing(sql):
            calls.append(sql)
            raise db.DatabaseError('SQL 执行失败：no such table: t_report_config')

        ops_service.db.execute_app_schema = fail_missing
        try:
            await ops_service.flush()
        finally:
            ops_service.db.execute_app_schema = original
        self.assertEqual(len(calls), 1, 'missing table should stop retrying per row or pruning')
