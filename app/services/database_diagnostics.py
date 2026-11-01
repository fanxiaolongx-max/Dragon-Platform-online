"""Bounded diagnostics for the assigned app/business schemas. No records or credentials in reports."""
import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from app import db
from app.config import settings, configuration_origins
from app.core.diagnostic_safety import clean, error_summary, group_name
from app.core.runtime_diagnostics import snapshot
from app.core.logger import logger
from app.core.exceptions import QueryValidationError
from app.utils.sql_contract import assert_read_query

DEFAULT_TABLE = 'nc_op_sa_sr_problem_detail_all_bg_dwd'
APP_TABLES = ('t_report_template', 't_report_block', 't_data_element', 't_data_source', 't_report_config')
CHECKS = [
    ('configuration', '环境配置 / Configuration'),
    ('datasources', '基座数据源接口 / Datasource endpoint'),
    ('app-basic', '应用库基本查询 / App query'),
    ('business-basic', '业务库基本查询 / Business query'),
    ('app-metadata', '应用库元数据 / App metadata'),
    ('business-tables', '业务表目录 / Business catalog'),
    ('columns-simple', '字段元数据基本语法 / Basic column metadata'),
    ('columns-current', '当前字段接口 SQL / Current column SQL'),
    ('table-plain', '目标表无引号 / Unquoted table'),
    ('table-backtick', '目标表反引号 / Backtick table'),
    ('table-double', '目标表双引号 / Double quoted table'),
    ('pagination', '分页 LIMIT/OFFSET / Pagination'),
    ('aggregate', '空结果聚合 / Empty aggregation'),
    ('guard', '本地只读 SQL 守卫 / Local SQL guard'),
] + [('app-table:' + t, '应用表 / App table: ' + t) for t in APP_TABLES]

def identifier(table):
    table = table.strip() or DEFAULT_TABLE
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', table):
        raise QueryValidationError('表名仅支持字母、数字和下划线 / Invalid table name')
    return table

def catalog():
    path = Path(__file__).resolve().parents[2] / 'static/data/all_tables.json'
    if not path.is_file():
        return []
    names = json.loads(path.read_text()).get('tables', [])
    return sorted({item['t'] for item in names if isinstance(item, dict) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', item.get('t', ''))})[:500]

def configuration():
    # Presence/transport flags only. No URLs, schema UUIDs, datasource identities or environment dump.
    return {'version': settings.APP_VERSION, 'hosted': bool(__import__('os').environ.get('PLATFORM_DATA_API')),
            'queryUrlConfigured': bool(settings.BASE_QUERY_URL), 'appSchemaConfigured': bool(settings.APP_SCHEMA),
            'businessAssigned': bool(settings.BUSINESS_DATASOURCE_NAME), 'appDatasourceConfigured': settings.APP_DATASOURCE_ID not in ('', None),
            'identityInjection': settings.INJECT_IDENTITY_HEADERS, 'tlsVerification': settings.HTTP_VERIFY_SSL,
            'httpTimeoutSeconds': settings.HTTP_TIMEOUT, 'businessDatasourceName': group_name(settings.BUSINESS_DATASOURCE_NAME),
            'configurationOrigins': configuration_origins(), 'runtime': snapshot(),
            'businessValueShape': {'length': len(settings.BUSINESS_DATASOURCE_NAME), 'hasOuterWhitespace': settings.BUSINESS_DATASOURCE_NAME != settings.BUSINESS_DATASOURCE_NAME.strip(), 'hasControlCharacters': any(ord(c) < 32 for c in settings.BUSINESS_DATASOURCE_NAME)}}

def datasource_match(body):
    # Compare names only; do not export other data sources, credentials or connection strings.
    candidates = [body.get('data'), body.get('rows'), body.get('list')]
    data = body.get('data')
    if isinstance(data, dict):
        candidates += [data.get(key) for key in ('rows', 'list', 'items', 'datasources', 'dataSources')]
    rows = next((value for value in candidates if isinstance(value, list)), None)
    configured = settings.BUSINESS_DATASOURCE_NAME
    names = []
    for row in rows or []:
        if isinstance(row, str): names.append(row)
        elif isinstance(row, dict):
            names.extend(str(row[key]) for key in ('name', 'datasourceName', 'dataSourceName', 'groupName') if isinstance(row.get(key), str))
    return {'configuredBusinessName': group_name(configured), 'configuredNameListed': configured in names if names or rows == [] else None,
            'catalogParsed': rows is not None, 'catalogItemCount': len(rows) if rows is not None else None,
            'namesComparable': bool(names) or rows == [], 'otherNamesExported': False}


def manifest(table='', full=False):
    table = identifier(table)
    checks = [{'id': key, 'label': label, 'table': table} for key, label in CHECKS]
    if full:
        checks += [{'id': 'scan-columns', 'label': '字段扫描 / Columns: ' + t, 'table': t} for t in catalog()]
    return {'schemaVersion': 1, 'configuration': configuration(), 'checks': checks,
            'coverage': {'readOnly': True, 'fullCatalog': full, 'catalogIsStatic': True,
                         'excluded': ['INSERT/UPDATE/DELETE', 'DDL / schema deployment', 'model calls', 'other databases', 'business record export']}}

def statement(key, table):
    name = table.replace("'", "''")
    if key in ('app-basic', 'business-basic'):
        return 'app' if key == 'app-basic' else 'netcare', 'SELECT 1 AS probe'
    if key == 'app-metadata':
        schema = settings.APP_SCHEMA.replace("'", "''")
        return 'app', f"SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA='{schema}' LIMIT 1"
    if key == 'business-tables':
        return 'netcare', "SELECT TABLE_NAME FROM information_schema.TABLES WHERE LOWER(TABLE_SCHEMA)='netcare' AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME LIMIT 1"
    if key in ('columns-simple', 'scan-columns'):
        return 'netcare', f"SELECT column_name FROM information_schema.columns WHERE table_name='{name}' LIMIT 1"
    if key == 'columns-current':
        return 'netcare', f"SELECT COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT, ORDINAL_POSITION FROM information_schema.COLUMNS WHERE LOWER(TABLE_SCHEMA)='netcare' AND LOWER(TABLE_NAME)='{name.lower()}' ORDER BY ORDINAL_POSITION"
    if key.startswith('app-table:'):
        app_table = key.split(':', 1)[1]
        if app_table not in APP_TABLES:
            raise QueryValidationError('未知应用表检查')
        return 'app', f'SELECT * FROM {app_table} WHERE 1=0'
    target = {'table-plain': table, 'table-backtick': '`' + table + '`', 'table-double': '"' + table + '"'}.get(key)
    if target:
        return 'netcare', f'SELECT * FROM {target} WHERE 1=0'
    if key == 'pagination':
        return 'netcare', f'SELECT * FROM {table} WHERE 1=0 LIMIT 1 OFFSET 0'
    if key == 'aggregate':
        return 'netcare', f'SELECT COUNT(*) AS probe_count FROM {table} WHERE 1=0'
    raise QueryValidationError('未知测试项 / Unknown probe')

async def probe(key, table=''):
    table = identifier(table)
    if key not in {item[0] for item in CHECKS} | {'scan-columns'}:
        raise QueryValidationError('未知测试项 / Unknown probe')
    started = time.monotonic()
    result = {'id': key, 'table': table, 'requestId': str(uuid.uuid4()), 'at': datetime.now(timezone.utc).isoformat(), 'runtime': snapshot(), 'status': 'pass', 'upstream': []}
    def observe(response, body, request):
        if len(result['upstream']) >= 4:
            return
        code = body.get('code') if isinstance(body, dict) else None
        result['upstream'].append({'httpStatus': response.status_code if response is not None else None, 'code': clean(code),
                                   'message': error_summary(body) if response is None or response.is_error or code not in (0, '0', None) else '',
                                   'requestId': clean(response.headers.get('x-request-id', '')) if response is not None else '', 'request': request})
    token = db.request_observer.set(observe)
    try:
        async def execute():
            if key == 'configuration':
                result['configuration'] = configuration()
                if not all(result['configuration'][k] for k in ('queryUrlConfigured', 'appSchemaConfigured', 'businessAssigned', 'appDatasourceConfigured')):
                    raise QueryValidationError('基座配置缺项 / Missing base configuration')
            elif key == 'datasources':
                body = await db._base_request('GET', db._base_datasources_url())
                if body.get('code') not in (0, '0'):
                    raise QueryValidationError(error_summary(body) or '数据源接口业务响应失败')
                result['datasourceMatch'] = datasource_match(body)
                if result['datasourceMatch']['configuredNameListed'] is False:
                    result.update(status='warning', message='运行时业务组未在基座数据源清单中匹配；请核对基座分配、注入值与旧 .env，不会自动切换其他库')
            elif key == 'guard':
                for sql in ('DELETE FROM t_report_config', 'CREATE TABLE diagnostic_probe(id INT)', "ATTACH DATABASE 'other.db' AS other"):
                    try:
                        assert_read_query(sql)
                    except QueryValidationError:
                        continue
                    raise QueryValidationError('只读守卫未拒绝写入或跨库命令')
                result['message'] = 'Local validator only; no forbidden SQL was sent to the base'
            else:
                source, sql = statement(key, table)
                result.update(source=source, sql=sql.replace(settings.APP_SCHEMA, '<assigned-app-schema>') if settings.APP_SCHEMA else sql)
                rows = await (db.query_app_schema if source == 'app' else db.query_business)(sql, limit=1)
                result['rowCount'] = len(rows)
                if key in ('columns-simple', 'columns-current', 'scan-columns', 'app-metadata', 'business-tables') and not rows:
                    result.update(status='warning', message='查询成功但未返回元数据；静态目录不证明实际表存在 / No metadata returned')
        await asyncio.wait_for(execute(), timeout=20)
    except Exception as error:
        result.update(status='fail', errorType=type(error).__name__, message=clean(getattr(error, 'message', str(error))) or 'Timeout / 请求超时')
    finally:
        db.request_observer.reset(token)
    result['ms'] = round((time.monotonic() - started) * 1000)
    if result['status'] != 'pass':
        logger.warning('DATABASE_PROBE ' + json.dumps({'requestId': result['requestId'], 'bootId': snapshot()['bootId'], 'probe': key, 'table': table, 'status': result['status'], 'baseRequestIds': [item['request']['requestId'] for item in result['upstream']]}, ensure_ascii=False))
    return result
