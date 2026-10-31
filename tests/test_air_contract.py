"""AIR runs through the same REST contract; SQLite exists only in this test fake base."""
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
        self.original_client, self.original_dialect = db._client, db._dialect_checked
        db._dialect_checked = False
        db._client = httpx.AsyncClient(transport=httpx.MockTransport(self.handle), trust_env=False)

    async def asyncTearDown(self):
        await db._client.aclose()
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


class DeploymentSchemaTests(unittest.TestCase):
    def test_old_platform_cannot_silently_claim_base_compatibility(self):
        with patch.dict('os.environ', {'PLATFORM_APP_SLUG': 'fixture', 'PLATFORM_APP_DATABASE_CONTRACT': 'platform'}):
            with self.assertRaisesRegex(RuntimeError, '更新平台'):
                assert_host_contract()
        with patch.dict('os.environ', {'PLATFORM_APP_SLUG': 'fixture', 'PLATFORM_APP_DATABASE_CONTRACT': 'digital-human'}):
            assert_host_contract()

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
