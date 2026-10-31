"""AIR runs through the same REST contract; SQLite exists only in this test fake base."""
import asyncio
import ast
import json
import re
import sqlite3
import unittest
from unittest.mock import patch
from pathlib import Path

import httpx
from app import db
from app.config import settings
from app.core.exceptions import DatabaseError, QueryValidationError
from app.services import air_service
from app.utils.sql_contract import assert_app_write, assert_host_contract

ROOT = Path(__file__).resolve().parents[1]
TABLES = {'t_report_template', 't_report_block', 't_report_config', 't_data_element', 't_data_source'}


class AirContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connection = sqlite3.connect(':memory:', isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript((ROOT / 'db/init.sqlite.sql').read_text())
        self.requests = []
        self.original_settings = {key: getattr(settings, key) for key in ('BASE_QUERY_URL', 'APP_DATASOURCE_ID', 'APP_SCHEMA', 'BUSINESS_DATASOURCE_NAME')}
        settings.BASE_QUERY_URL = 'https://base.fixture/dh/query'
        settings.APP_DATASOURCE_ID = 'app'
        settings.APP_SCHEMA = 'fixture-schema'
        settings.BUSINESS_DATASOURCE_NAME = 'fixture-business'
        self.original_gate, self.original_save_lock = db._gate, air_service._save_lock
        db._gate = db.BaseRequestGate()
        air_service._save_lock = asyncio.Lock()
        self.original_client, self.original_dialect = db._client, db._dialect_checked
        db._dialect_checked = False
        db._client = httpx.AsyncClient(transport=httpx.MockTransport(self.handle), trust_env=False)

    async def asyncTearDown(self):
        await db._client.aclose()
        db._gate, air_service._save_lock = self.original_gate, self.original_save_lock
        db._client, db._dialect_checked = self.original_client, self.original_dialect
        for key, value in self.original_settings.items():
            setattr(settings, key, value)
        self.connection.close()

    def handle(self, request):
        body = json.loads(request.content)
        self.requests.append((request.url.path, body))
        if 'datasourceName' in body:
            self.assertLessEqual(body['limit'], 1000)
            self.assertEqual(request.url.path, '/dh/query')
            self.assertEqual(body['datasourceName'], 'fixture-business')
            self.assertNotIn('schema', body)
            return httpx.Response(200, json={'code': 0, 'data': {'rows': [{'total': 12}]}})
        self.assertEqual(body['datasourceId'], 'app')
        self.assertEqual(body['schema'], 'fixture-schema')
        sql = body['sql']
        try:
            if request.url.path == '/dh/execute':
                assert_app_write(sql)
                result = self.connection.execute(sql)
                # Deliberately no lastInsertId: callers must query their own business key.
                response = {'affectedRows': result.rowcount}
            else:
                self.assertLessEqual(body['limit'], 1000)
                response = {'rows': [dict(row) for row in self.connection.execute(sql).fetchmany(body['limit'])]}
            return httpx.Response(200, json={'code': 0, 'data': response})
        except sqlite3.Error as error:
            return httpx.Response(200, json={'code': 500, 'message': str(error), 'data': None})

    async def test_air_crud_uses_existing_three_tables_and_never_requires_insert_id(self):
        html = "<p>Owner's path C:\\report\\data</p>"
        doc = {'name': '契约测试', 'reportMonth': '2026-09', 'template': {}, 'style': {'prompt': '整体风格'},
               'chapters': [{'id': 'ch-1', 'title': {'zh': '概况'}, 'cells': [{'id': 'cell-1', 'prompt': '统计业务', 'span': 6,
               'height': 240, 'output': {'html': html}}]}]}
        saved = await air_service.save_document(doc)
        self.assertTrue(saved['id'].isdigit())
        self.assertEqual(saved['chapters'][0]['cells'][0]['output']['html'], html)
        self.assertEqual(saved['chapters'][0]['cells'][0]['prompt'], '统计业务')
        saved['name'] = '已修改'; saved['chapters'][0]['cells'][0]['prompt'] = '新的提示词'
        updated = await air_service.save_document(saved)
        self.assertEqual(updated['name'], '已修改')
        self.assertEqual(updated['chapters'][0]['cells'][0]['prompt'], '新的提示词')
        self.assertTrue(any(row['id'] == saved['id'] for row in await air_service.list_documents()))
        await air_service.delete_document(saved['id'])
        self.assertFalse(await air_service.list_documents())
        names = {row['name'] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        self.assertEqual(names, TABLES)
        for path, body in self.requests:
            if path.endswith('/execute'):
                self.assertRegex(body['sql'], r'^\s*(INSERT|UPDATE|DELETE)\b')

    async def test_internal_document_and_config_reads_paginate_past_1000_rows(self):
        self.connection.executemany("INSERT INTO t_report_template(id,name,description,content) VALUES(?,?,?,?)", [(i,'report',f'ai-report:{i}','{}') for i in range(1,1006)])
        self.assertEqual(len(await air_service.list_documents()),1005)
        self.connection.executemany("INSERT INTO t_report_block(id,report_id,block_key,chart_type,chart_data,order_no) VALUES(?,1,?,'ai-cell','{}',?)", [(i,f'cell-{i}',i) for i in range(1,1006)])
        self.connection.executemany("INSERT INTO t_report_config(report_id,block_id,section,config_text) VALUES(1,?,'prompt',?)", [(i,json.dumps({'prompt':f'prompt-{i}'})) for i in range(1,1006)])
        document=await air_service.read_document('1')
        cells=[cell for chapter in document['chapters'] for cell in chapter['cells']]
        self.assertEqual(len(cells),1005)
        self.assertEqual(cells[-1]['prompt'],'prompt-1005')
        self.assertTrue(any('OFFSET 1000' in body['sql'] for _,body in self.requests))

    async def test_missing_schema_fails_instead_of_creating_tables(self):
        for name in TABLES:
            self.connection.execute('DROP TABLE ' + name)
        with self.assertRaisesRegex(DatabaseError, 'no such table'):
            await air_service.list_documents()
        self.assertTrue(all(path.endswith('/query') for path, _ in self.requests))
        self.assertEqual(self.connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0], 0)

    async def test_ddl_and_unbounded_writes_fail_before_any_rest_request(self):
        for sql in ['CREATE TABLE bad(id INT)', 'ALTER TABLE t ADD x INT', 'DROP TABLE t', 'REPLACE INTO t VALUES(1)',
                    'DELETE FROM t', "UPDATE t SET value='where'", 'UPDATE t SET value=(SELECT 1 WHERE 1=1)', 'INSERT INTO t VALUES(1); DROP TABLE t']:
            with self.assertRaises(QueryValidationError, msg=sql):
                await db.base_execute_app_schema(sql)
        self.assertEqual(self.requests, [])
        assert_app_write("UPDATE t SET value='create; where' WHERE id=1")
        assert_app_write("INSERT INTO t(value) VALUES('SQL -- text; not comments')")
        assert_app_write("UPDATE t SET value='C:\\' WHERE id=1")
        assert_app_write("UPDATE t SET value='C:\\\\' WHERE id=1", backslash_escapes=True)

    async def test_business_query_is_read_only_and_uses_datasource_name(self):
        for sql in ['DELETE FROM orders WHERE id=1', 'WITH x AS(SELECT 1) DELETE FROM orders WHERE id=1']:
            with self.assertRaises(QueryValidationError):
                await db.base_query_business(sql)
        self.assertEqual(self.requests, [])
        rows = await db.query_business("SELECT count(*) AS total FROM orders WHERE month='2026-09'", 5000)
        self.assertEqual(rows, [{'total': 12}])
        self.assertEqual(self.requests[0][1]['datasourceName'], 'fixture-business')

    def virtual_gate(self):
        class Clock:
            now = 0.0
            async def sleep(self, delay):
                self.now += delay
                await asyncio.sleep(0)
        clock = Clock()
        db._gate = db.BaseRequestGate(clock=lambda: clock.now, sleep=clock.sleep)
        return clock

    async def use_handler(self, handler):
        await db._client.aclose()
        db._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)

    async def test_complete_template_saves_under_host_bucket_and_reuses_first_save_key(self):
        clock = self.virtual_gate()
        bucket = {"tokens": 40.0, "at": 0.0, "limited": 0}
        def limited(request):
            bucket["tokens"] = min(40, bucket["tokens"] + (clock.now - bucket["at"]) * 20)
            bucket["at"] = clock.now
            if bucket["tokens"] < 1:
                bucket["limited"] += 1
                return httpx.Response(429, json={"code": "HOSTED_DATA_RATE_LIMIT", "message": "limited"})
            bucket["tokens"] -= 1
            return self.handle(request)
        await self.use_handler(limited)
        doc = json.loads((ROOT / 'static/air/default-template.json').read_text())
        doc.update(reportMonth='2026-09', saveKey='stable-client-save')
        saved = await air_service.save_document(doc)
        initial_calls = len(self.requests)
        self.assertLessEqual(initial_calls, 13, 'full default template should use batched inserts')
        self.assertEqual(sum(len(c['cells']) for c in saved['chapters']), 18)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM t_report_config').fetchone()[0], 19)
        again = await air_service.save_document(doc)
        self.assertEqual(again['id'], saved['id'])
        self.assertEqual(self.connection.execute('SELECT count(*) FROM t_report_template').fetchone()[0], 1)
        self.assertEqual(bucket['limited'], 0)
        self.assertEqual([x['prompt'] for c in saved['chapters'] for x in c['cells']], [x['prompt'] for c in doc['chapters'] for x in c['cells']])

    async def test_explicit_http_and_business_limit_retry_after_then_succeed(self):
        clock = self.virtual_gate()
        attempts = []
        def limits(request):
            attempts.append(clock.now)
            if len(attempts) == 1:
                return httpx.Response(429, headers={'Retry-After': '2'}, text='busy')
            if len(attempts) == 2:
                return httpx.Response(200, json={'code': 429, 'message': 'busy'})
            return self.handle(request)
        await self.use_handler(limits)
        self.assertEqual(await db.query_app_schema('SELECT 1 AS n'), [{'n': 1}])
        self.assertGreaterEqual(attempts[1] - attempts[0], 2)
        self.assertGreaterEqual(attempts[2] - attempts[1], 1)

    async def test_persistent_limit_is_bounded_and_ambiguous_writes_are_never_replayed(self):
        self.virtual_gate()
        calls = []
        def limited(request):
            calls.append(request)
            return httpx.Response(429, json={'code': 'HOSTED_DATA_RATE_LIMIT'})
        await self.use_handler(limited)
        with self.assertRaises(DatabaseError) as caught:
            await db.execute_app_schema("INSERT INTO t_report_template(name) VALUES('test')")
        self.assertEqual(caught.exception.code, 429)
        self.assertEqual(len(calls), 4)
        calls.clear()
        def ambiguous(request):
            calls.append(request)
            raise httpx.ReadTimeout('response lost', request=request)
        await self.use_handler(ambiguous)
        with self.assertRaises(DatabaseError):
            await db.execute_app_schema("INSERT INTO t_report_template(name) VALUES('test')")
        self.assertEqual(len(calls), 1)

    async def test_partial_write_timeout_resumes_same_report_without_duplicate_rows(self):
        self.virtual_gate()
        for index, table in enumerate(['t_report_template', 't_report_block', 't_report_config'], 1):
            failed = False
            def timeout_after_insert(request):
                nonlocal failed
                response = self.handle(request)
                sql = json.loads(request.content)['sql']
                if not failed and sql.startswith('INSERT INTO ' + table + ' '):
                    failed = True
                    raise httpx.ReadTimeout('committed but response lost', request=request)
                return response
            await self.use_handler(timeout_after_insert)
            doc = json.loads((ROOT / 'static/air/default-template.json').read_text())
            doc.update(reportMonth='2026-09', saveKey='resumable-' + table, saveAs=True)
            with self.assertRaises(DatabaseError):
                await air_service.save_document(doc)
            saved = await air_service.save_document(doc)
            self.assertTrue(saved['id'].isdigit())
            self.assertEqual(self.connection.execute('SELECT count(*) FROM t_report_template').fetchone()[0], index)
            self.assertEqual(self.connection.execute('SELECT count(*) FROM t_report_block').fetchone()[0], 18 * index)
            self.assertEqual(self.connection.execute('SELECT count(*) FROM t_report_config').fetchone()[0], 19 * index)

    async def test_only_explicit_save_as_creates_second_report_in_same_month(self):
        self.virtual_gate()
        doc={'reportMonth':'2026-10','name':'same','saveKey':'first','chapters':[]}
        first=await air_service.save_document(doc)
        with self.assertRaisesRegex(Exception,'该月份已有月报'):
            await air_service.save_document({**doc,'saveKey':'another-tab'})
        copy=await air_service.save_document({**doc,'saveKey':'explicit-copy','saveAs':True})
        self.assertNotEqual(first['id'],copy['id'])
        self.assertEqual(copy['reportKind'],'copy')
        listing=await air_service.list_documents()
        self.assertEqual(sum(x['isDefault'] for x in listing),1)
        await air_service.save_document(copy)
        with self.assertRaisesRegex(QueryValidationError,'切换月份'):
            await air_service.save_document({**first,'reportMonth':'2026-11'})
        next_month=await air_service.save_document({**doc,'reportMonth':'2026-11','saveKey':'november'})
        self.assertNotEqual(first['id'],next_month['id'])
        self.assertEqual((await air_service.read_document(first['id']))['reportMonth'],'2026-10')

    async def test_legacy_same_month_duplicates_are_retained_as_history(self):
        self.virtual_gate()
        for i in [1,2]:
            self.connection.execute('INSERT INTO t_report_template(id,name,description,content) VALUES(?,?,?,?)',(i,'same','ai-report:legacy'+str(i),json.dumps({'reportMonth':'2026-10','chapters':[]})))
        listing=await air_service.list_documents()
        self.assertEqual(len(listing),2)
        self.assertEqual(sum(x['isDefault'] for x in listing),1)
        history=next(x for x in listing if x['reportKind']=='history')
        loaded=await air_service.read_document(history['id'])
        self.assertEqual(loaded['reportKind'],'history')
        await air_service.save_document(loaded)
        self.assertEqual(sum(x['isDefault'] for x in await air_service.list_documents()),1)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM t_report_template').fetchone()[0],2)

    async def test_batch_insert_chunks_by_utf8_size_and_preserves_quotes(self):
        self.virtual_gate()
        text = "字'" * 20_000
        rows = [[1, None, 'test', text, '', ''] for _ in range(3)]
        await air_service._insert_rows('t_report_config', ['report_id','block_id','section','config_text','created_at','updated_at'], rows)
        inserts = [body['sql'] for path, body in self.requests if path.endswith('/execute')]
        self.assertGreater(len(inserts), 1)
        self.assertTrue(all(len(sql.encode('utf-8')) < 200_000 for sql in inserts))
        self.assertEqual([row[0] for row in self.connection.execute('SELECT config_text FROM t_report_config')], [text] * 3)

    async def test_concurrent_first_saves_with_same_key_return_same_report(self):
        self.virtual_gate()
        doc = {'saveKey': 'concurrent-save', 'name': 'same', 'reportMonth': '2026-09', 'chapters': []}
        one, two = await asyncio.gather(air_service.save_document(doc), air_service.save_document(doc))
        self.assertEqual(one['id'], two['id'])
        self.assertEqual(self.connection.execute('SELECT count(*) FROM t_report_template').fetchone()[0], 1)


class DeploymentSchemaTests(unittest.TestCase):
    def test_host_contract_smooth_compatibility(self):
        # 兼容旧平台或非 digital-human 配置：记录警告并返回 False，不再抛致命异常阻断启动
        with patch.dict('os.environ', {'PLATFORM_APP_SLUG': 'fixture', 'PLATFORM_APP_DATABASE_CONTRACT': 'platform'}):
            self.assertFalse(assert_host_contract())
        # 数字人基座契约配置：正常通过
        with patch.dict('os.environ', {'PLATFORM_APP_SLUG': 'fixture', 'PLATFORM_APP_DATABASE_CONTRACT': 'digital-human'}):
            self.assertTrue(assert_host_contract())
        # 真实数字人基座环境（无 PLATFORM_APP_SLUG）：正常通过
        with patch.dict('os.environ', {}, clear=True):
            self.assertTrue(assert_host_contract())

    def test_mysql_and_sqlite_deploy_the_same_five_tables_and_columns(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.executescript((ROOT / 'db/init.sqlite.sql').read_text())
        mysql = (ROOT / 'db/init.sql').read_text()
        tables = {}
        for match in re.finditer(r'CREATE TABLE IF NOT EXISTS `?(\w+)`?\s*\((.*?)\)\s*ENGINE', mysql, re.S | re.I):
            tables[match[1]] = set(re.findall(r'^\s*`([^`]+)`\s+', match[2], re.M))
        self.assertEqual(set(tables), TABLES)
        for name, columns in tables.items():
            self.assertEqual(columns, {row[1] for row in conn.execute('PRAGMA table_info('+name+')')})
        conn.execute("INSERT INTO t_report_template(id,name,title) VALUES(1,'customer','Existing customer report')")
        conn.executescript((ROOT / 'db/init.sqlite.sql').read_text())
        self.assertEqual(conn.execute('SELECT title FROM t_report_template WHERE id=1').fetchone()[0], 'Existing customer report')
        for _ in range(2):
            conn.executescript((ROOT / 'db/upgrade.sqlite.sql').read_text())
        self.assertEqual(conn.execute('SELECT title FROM t_report_template WHERE id=1').fetchone()[0], 'Existing customer report')
        self.assertNotRegex((ROOT / 'db/upgrade.sql').read_text(), r'(?i)\b(?:INSERT|UPDATE|DELETE|DROP)\s')
        fresh = sqlite3.connect(':memory:')
        self.addCleanup(fresh.close)
        fresh.executescript((ROOT / 'db/upgrade.sqlite.sql').read_text())
        seed = mysql[mysql.index('-- 初始数据'):]
        fresh.executescript(re.sub(r'ON DUPLICATE KEY UPDATE[^;]+;', ';', seed))
        for name, key in [('t_data_source','source_key'),('t_data_element','element_key')]:
            self.assertEqual(list(conn.execute('SELECT * FROM '+name+' ORDER BY '+key)), list(fresh.execute('SELECT * FROM '+name+' ORDER BY '+key)))
        self.assertEqual(fresh.execute('SELECT count(*) FROM t_report_template').fetchone()[0],0)


    def test_application_has_no_direct_database_driver_imports(self):
        for file in (ROOT / 'app').rglob('*.py'):
            for node in ast.walk(ast.parse(file.read_text())):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
                self.assertFalse(any(name.split('.')[0] in {'sqlite3','sqlalchemy','pymysql','redis'} for name in names), str(file))


if __name__ == '__main__':
    unittest.main()
