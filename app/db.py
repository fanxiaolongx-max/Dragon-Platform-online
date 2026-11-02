# -*- coding: utf-8 -*-
"""数据库访问层 — 通过基座 REST API 访问数据。

通过 httpx 调用基座 REST API（API-Q1~Q5）访问数据。
环境变量配置：BASE_QUERY_URL / APP_DATASOURCE_ID / APP_SCHEMA / BUSINESS_DATASOURCE_NAME。
"""
import asyncio
from contextvars import ContextVar
import hashlib
import json
import re
import uuid
from urllib.parse import urlsplit
import time
from email.utils import parsedate_to_datetime

import httpx

from app.config import (
    BETA_QUERY_URL,
    BETA_SCHEMA,
    KNOWN_BUSINESS_DATASOURCES,
    PROD_QUERY_URL,
    PROD_SCHEMA,
    settings,
)
from app.core.exceptions import DatabaseError, QueryValidationError
from app.core.logger import logger
from app.core.diagnostic_safety import clean, group_name
from app.core.runtime_diagnostics import BOOT_ID
from app.utils import sql_helper
from app.utils.sql_contract import assert_app_write, assert_read_query


# --------------------------------------------------------------------
# 基座 API 地址拼接
# --------------------------------------------------------------------

def _base_execute_url() -> str:
    """API-Q2 写操作地址：将末尾 /query 替换为 /execute"""
    return settings.BASE_QUERY_URL.replace("/query", "/execute")


def _base_datasources_url() -> str:
    """API-Q3 数据源列表地址"""
    return settings.BASE_QUERY_URL + "/datasources"


def _base_find_table_url() -> str:
    """API-Q5 按表名反查地址"""
    return settings.BASE_QUERY_URL.replace("/query", "/query/find-table-datasource")


# --------------------------------------------------------------------
# 基座 API 客户端（模块级复用，避免每次请求重新建立 TLS 连接）
# --------------------------------------------------------------------

_client: httpx.AsyncClient | None = None
request_observer = ContextVar('base_request_observer', default=None)
# 每次基座请求的最终结果（重试之后）通知这些监听器，供交互日志与表健康状态使用；监听器不能抛错也不能阻塞。
request_listeners: list = []


def _get_client() -> httpx.AsyncClient:
    """返回复用的 AsyncClient。首次调用时创建，连接池与 TLS 会话长期复用。"""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=settings.HTTP_TIMEOUT,
            verify=settings.HTTP_VERIFY_SSL,
            trust_env=False,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=20),
        )
    return _client


async def close_client() -> None:
    """关闭全局客户端（应用退出时调用）"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class BaseRequestGate:
    """应用内所有取数共享节奏，给基座的其它请求留出额度；只重试明确未执行的限流响应。"""
    def __init__(self, interval=0.1, clock=time.monotonic, sleep=asyncio.sleep):
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.lock = asyncio.Lock()
        self.next_at = 0.0

    async def wait(self):
        async with self.lock:
            while self.next_at > self.clock():
                await self.sleep(self.next_at - self.clock())
            self.next_at = self.clock() + self.interval

    def cooldown(self, seconds):
        self.next_at = max(self.next_at, self.clock() + seconds)


_gate = BaseRequestGate()


def _retry_after(response, attempt):
    value = response.headers.get("Retry-After", "")
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            seconds = 0
    return max(0.5 * 2 ** attempt, seconds)


async def _base_request(method, url, **kwargs):
    started = time.monotonic()
    try:
        data = await _base_request_attempts(method, url, **kwargs)
    except Exception as exc:
        _notify(method, url, kwargs, None, exc, started)
        raise
    _notify(method, url, kwargs, data, None, started)
    return data


def _notify(method, url, kwargs, data, error, started):
    if not request_listeners:
        return
    event = {'method': method, 'path': urlsplit(str(url)).path, 'payload': kwargs.get('json') or {},
             'params': kwargs.get('params') or {}, 'data': data, 'error': error,
             'ms': round((time.monotonic() - started) * 1000)}
    for listener in list(request_listeners):
        try:
            listener(event)
        except Exception as exc:
            logger.debug(f"基座请求监听器出错：{exc}")


async def _base_request_attempts(method, url, **kwargs):
    request_id = str(uuid.uuid4())
    for attempt in range(4):
        await _gate.wait()
        # 网络超时或其它模糊失败不自动重发写入，防止已成功的 INSERT 被再次执行。
        started = time.monotonic()
        observer = request_observer.get()
        payload = kwargs.get('json') or {}
        metadata = {'requestId': request_id, 'bootId': BOOT_ID, 'method': method,
                    'endpointPath': clean(re.sub(r'/~[^/]+|/[a-fA-F0-9-]{36}', '/[identity]', urlsplit(str(url)).path)),
                    'scope': 'app' if 'schema' in payload else 'business' if 'datasourceName' in payload else 'metadata',
                    'businessDatasourceName': group_name(payload.get('datasourceName')),
                    'payloadKeys': sorted(key for key in payload if key in ('datasourceId', 'schema', 'datasourceName', 'sql', 'limit')),
                    'sqlFingerprint': hashlib.sha256(str(payload.get('sql', '')).encode()).hexdigest()[:16],
                    'attempt': attempt + 1, 'ms': round((time.monotonic() - started) * 1000)}
        try:
            response = await _get_client().request(method, url, **kwargs)
        except httpx.RequestError as error:
            metadata.update(ms=round((time.monotonic() - started) * 1000), networkErrorType=type(error).__name__)
            logger.warning('BASE_REQUEST_FAILURE ' + json.dumps(metadata, ensure_ascii=False))
            if observer:
                observer(None, {'code': 'NETWORK_ERROR', 'message': type(error).__name__}, metadata)
            raise
        metadata['ms'] = round((time.monotonic() - started) * 1000)
        try:
            data = response.json()
        except ValueError:
            data = None
        if observer:
            observer(response, data, metadata)
        code = data.get("code") if isinstance(data, dict) else None
        limited = response.status_code == 429 or code in (429, "429", "HOSTED_DATA_RATE_LIMIT")
        if limited:
            delay = _retry_after(response, attempt)
            _gate.cooldown(delay)
            if attempt < 3 and delay <= 10:
                continue
            error = DatabaseError("请求限流，已自动等待重试；请稍后保存同一份月报，未保存内容仍保留在页面中")
            error.code = 429
            error.data = {"retryAfter": delay}
            raise error
        if response.is_error:
            raw_msg = (data.get('message') or data.get('msg') or data.get('error')) if isinstance(data, dict) else ''
            if not raw_msg and response.text:
                raw_msg = response.text[:200]
            err_msg_clean = clean(raw_msg) if raw_msg else ''
            log_meta = {**metadata, 'httpStatus': response.status_code, 'code': clean(code)}
            if err_msg_clean:
                log_meta['message'] = err_msg_clean
            logger.warning('BASE_REQUEST_FAILURE ' + json.dumps(log_meta, ensure_ascii=False))
            detail = f"（HTTP {response.status_code}，{err_msg_clean}，请求编号 {request_id}）" if err_msg_clean else f"（HTTP {response.status_code}，请求编号 {request_id}）"
            raise DatabaseError(f"基座 API 请求失败{detail}", data={'requestId': request_id, 'httpStatus': response.status_code, 'message': err_msg_clean})
        if not isinstance(data, dict):
            raise DatabaseError("基座 API 返回了无效的 JSON 响应")
        return data


async def base_query_app_schema(sql: str, limit: int = 100) -> dict:
    """API-Q1: 查询应用 schema 内的表（datasourceId + schema 限定）"""
    assert_read_query(sql, backslash_escapes=sql_helper.BACKSLASH_ESCAPES)
    return await _base_request("POST",
        settings.BASE_QUERY_URL,
        json={
            "datasourceId": settings.APP_DATASOURCE_ID,
            "schema": settings.APP_SCHEMA,
            "sql": sql,
            "limit": max(1, min(1000, int(limit))),
        },
    )


async def base_execute_app_schema(sql: str) -> dict:
    """API-Q2: 写操作（INSERT/UPDATE/DELETE）到应用 schema"""
    assert_app_write(sql, backslash_escapes=sql_helper.BACKSLASH_ESCAPES)
    # 身份头 x-app-id / x-app-level 由基座 venv sitecustomize.py 自动注入，应用禁止手动设置
    # 本地开发（非基座环境）时 sitecustomize.py 不存在，通过 INJECT_IDENTITY_HEADERS 开关手动注入
    app_id = settings.APP_UUID or settings.APP_SCHEMA
    headers = (
        {"x-app-id": app_id, "x-app-level": settings.APP_LEVEL}
        if settings.INJECT_IDENTITY_HEADERS
        else None
    )
    payload = {
        "datasourceId": settings.APP_DATASOURCE_ID,
        "schema": settings.APP_SCHEMA,
        "sql": sql,
    }
    try:
        return await _base_request("POST", _base_execute_url(), json=payload, headers=headers)
    except DatabaseError as exc:
        http_status = (exc.data or {}).get("httpStatus") if isinstance(getattr(exc, "data", None), dict) else None
        if headers is None and http_status in (401, 403) and app_id:
            settings.INJECT_IDENTITY_HEADERS = True
            return await _base_request(
                "POST",
                _base_execute_url(),
                json=payload,
                headers={"x-app-id": app_id, "x-app-level": settings.APP_LEVEL},
            )
        raise


def _extract_datasource_names(body: dict) -> list[str]:
    candidates = [body.get("data"), body.get("rows"), body.get("list")]
    data = body.get("data")
    if isinstance(data, dict):
        candidates += [data.get(key) for key in ("rows", "list", "items", "datasources", "dataSources")]
    rows = next((value for value in candidates if isinstance(value, list)), None)
    names: list[str] = []
    for row in rows or []:
        if isinstance(row, str):
            names.append(row)
        elif isinstance(row, dict):
            names.extend(
                str(row[key])
                for key in ("name", "datasourceName", "dataSourceName", "groupName")
                if isinstance(row.get(key), str)
            )
    return names


async def _adapt_business_datasource() -> bool:
    """当配置的业务数据源名称在当前基座不存在时，从 /datasources 清单匹配标准 NetCare 业务数据源。"""
    try:
        body = await _base_request("GET", _base_datasources_url(), timeout=5.0)
        if not isinstance(body, dict) or body.get("code") not in (0, "0"):
            return False
        names = _extract_datasource_names(body)
        if not names or settings.BUSINESS_DATASOURCE_NAME in names:
            return False
        for candidate in KNOWN_BUSINESS_DATASOURCES:
            if candidate in names:
                old_name = settings.BUSINESS_DATASOURCE_NAME
                settings.BUSINESS_DATASOURCE_NAME = candidate
                logger.info(f"业务数据源已自适应切换：{old_name} -> {candidate}")
                return True
        for name in names:
            if name.lower().startswith("netcare"):
                old_name = settings.BUSINESS_DATASOURCE_NAME
                settings.BUSINESS_DATASOURCE_NAME = name
                logger.info(f"业务数据源已自适应切换：{old_name} -> {name}")
                return True
    except Exception as exc:
        logger.debug(f"业务数据源自适应探测跳过：{exc}")
    return False


_DOUBLE_QUOTED_TABLE_RE = re.compile(
    r'\b(FROM|JOIN)\s+"([A-Za-z_][A-Za-z0-9_]*)"(?:\s*\.\s*"([A-Za-z_][A-Za-z0-9_]*)")?',
    re.IGNORECASE,
)


def _normalize_table_quotes(sql: str) -> str:
    """将 FROM/JOIN 后的双引号表名（GaussDB/PostgreSQL 风格）转换为 MySQL/SQLite 兼容的反引号。"""
    return _DOUBLE_QUOTED_TABLE_RE.sub(
        lambda m: f"{m.group(1)} `{m.group(2)}`.`{m.group(3)}`" if m.group(3) else f"{m.group(1)} `{m.group(2)}`",
        sql,
    )


async def base_query_business(sql: str, limit: int = 100) -> dict:
    """API-Q1: 查询业务库（只读，按业务库组名 datasourceName）"""
    assert_read_query(sql, backslash_escapes=sql_helper.BACKSLASH_ESCAPES)
    if not settings.BUSINESS_DATASOURCE_NAME:
        raise RuntimeError("未注入 BUSINESS_DATASOURCE_NAME，请创建应用时指定业务数据库")
    normalized_sql = _normalize_table_quotes(sql)
    try:
        body = await _base_request("POST",
            settings.BASE_QUERY_URL,
            json={
                "datasourceName": settings.BUSINESS_DATASOURCE_NAME,
                "sql": normalized_sql,
                "limit": max(1, min(1000, int(limit))),
            },
        )
        # Some base versions encode the same missing-source failure in HTTP 200.
        if body.get('code') not in (0, '0') and '数据源不存在' in str(body.get('message', '')):
            raise DatabaseError(clean(body.get('message')))
        return body
    except DatabaseError as exc:
        if (
            "数据源不存在" in str(exc)
            and settings.BUSINESS_DATASOURCE_NAME.lower().startswith("netcare")
            and await _adapt_business_datasource()
        ):
            return await _base_request("POST",
                settings.BASE_QUERY_URL,
                json={
                    "datasourceName": settings.BUSINESS_DATASOURCE_NAME,
                    "sql": normalized_sql,
                    "limit": max(1, min(1000, int(limit))),
                },
            )
        raise


async def base_find_table_datasource(table_name: str) -> dict:
    """API-Q5: 按表名反查所属业务数据源组"""
    return await _base_request("GET", _base_find_table_url(), params={"table": table_name})


async def check_base_api() -> bool:
    """基座 API 连通性检查（调用 API-Q3 GET /datasources）"""
    try:
        async with httpx.AsyncClient(
            timeout=5, verify=settings.HTTP_VERIFY_SSL, trust_env=False
        ) as client:
            r = await client.get(_base_datasources_url())
            return r.status_code == 200 and r.json().get("code") == 0
    except Exception as exc:
        logger.warning(f"基座 API 连通失败：{exc}")
        return False


# --------------------------------------------------------------------
# 统一数据访问门面
# --------------------------------------------------------------------

async def query_app_schema(sql: str, limit: int = 100) -> list[dict]:
    """查询应用 schema 内数据，返回 rows 列表。"""
    try:
        resp = await base_query_app_schema(sql, limit)
    except (QueryValidationError, DatabaseError):
        raise
    except Exception as exc:
        raise DatabaseError(f"基座 API 请求失败：{exc}")
    if resp.get("code") != 0:
        raise DatabaseError(resp.get("message", "基座查询失败"))
    return resp.get("data", {}).get("rows", [])


async def execute_app_schema(sql: str) -> int:
    """写操作（INSERT/UPDATE/DELETE），返回 affectedRows。"""
    try:
        resp = await base_execute_app_schema(sql)
    except (QueryValidationError, DatabaseError):
        raise
    except Exception as exc:
        raise DatabaseError(f"基座 API 请求失败：{exc}")
    if resp.get("code") != 0:
        raise DatabaseError(resp.get("message", "基座写操作失败"))
    return resp.get("data", {}).get("affectedRows", 0)


async def query_business(sql: str, limit: int = 100) -> list[dict]:
    """查询业务库（只读），返回 rows 列表。"""
    try:
        resp = await base_query_business(sql, limit)
    except (QueryValidationError, DatabaseError):
        raise
    except Exception as exc:
        raise DatabaseError(f"基座 API 请求失败：{exc}")
    if resp.get("code") != 0:
        raise DatabaseError(resp.get("message", "基座查询失败"))
    return resp.get("data", {}).get("rows", [])


_dialect_checked = False


async def _probe_schema_has_tables(query_url: str, schema: str) -> bool:
    """轻量探测指定 (query_url, schema) 是否存在应用表。"""
    if not query_url or not schema:
        return False
    safe_schema = schema.replace("'", "''")
    sql = f"SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA='{safe_schema}' LIMIT 1"
    try:
        body = await _base_request(
            "POST", query_url,
            json={
                "datasourceId": settings.APP_DATASOURCE_ID,
                "schema": schema,
                "sql": sql,
                "limit": 1,
            },
            timeout=3.0,
        )
        if not isinstance(body, dict) or body.get("code") not in (0, "0"):
            return False
        rows = (body.get("data") or {}).get("rows") or []
        return len(rows) > 0
    except Exception:
        return False


async def _ensure_online_profile() -> None:
    """在测试/生产数字人基座之间主动探测并自适应切换 Schema 与 URL。"""
    import os
    if os.environ.get("PLATFORM_DATA_API"):
        return
    if settings.APP_SCHEMA not in (BETA_SCHEMA, PROD_SCHEMA):
        return
    if await _probe_schema_has_tables(settings.BASE_QUERY_URL, settings.APP_SCHEMA):
        return
    alt_schema = PROD_SCHEMA if settings.APP_SCHEMA == BETA_SCHEMA else BETA_SCHEMA
    alt_url = PROD_QUERY_URL if settings.APP_SCHEMA == BETA_SCHEMA else BETA_QUERY_URL
    candidates = [
        (settings.BASE_QUERY_URL, alt_schema),
        (alt_url, alt_schema),
        (alt_url, settings.APP_SCHEMA),
    ]
    for cand_url, cand_schema in candidates:
        if await _probe_schema_has_tables(cand_url, cand_schema):
            settings.BASE_QUERY_URL = cand_url
            settings.APP_SCHEMA = cand_schema
            settings.APP_UUID = cand_schema
            logger.info(f"检测到匹配的线上基座环境，已自动对齐 APP_SCHEMA={cand_schema[:8]}...")
            return


async def detect_sql_dialect() -> None:
    """探测应用库是否把反斜杠当转义符（MySQL 是，SQLite 否），只需成功探测一次。"""
    global _dialect_checked
    if _dialect_checked:
        return
    try:
        await _ensure_online_profile()
        rows = await query_app_schema("SELECT 'a\\\\b' AS v", limit=1)
        value = str(next(iter(rows[0].values()))) if rows else ""
        sql_helper.set_backslash_escapes(len(value) == 3)
        _dialect_checked = True
        logger.info(f"应用库字符串反斜杠转义：{'开启' if len(value) == 3 else '关闭'}")
    except Exception as exc:
        logger.warning(f"应用库方言探测失败，稍后写入前重试：{exc}")
