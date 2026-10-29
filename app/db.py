# -*- coding: utf-8 -*-
"""数据库访问层 — 通过基座 REST API 访问数据。

通过 httpx 调用基座 REST API（API-Q1~Q5）访问数据。
环境变量配置：BASE_QUERY_URL / APP_DATASOURCE_ID / APP_SCHEMA / BUSINESS_DATASOURCE_NAME。
"""
import httpx

from app.config import settings
from app.core.exceptions import DatabaseError
from app.core.logger import logger


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


async def base_query_app_schema(sql: str, limit: int = 100) -> dict:
    """API-Q1: 查询应用 schema 内的表（datasourceId + schema 限定）"""
    r = await _get_client().post(
        settings.BASE_QUERY_URL,
        json={
            "datasourceId": settings.APP_DATASOURCE_ID,
            "schema": settings.APP_SCHEMA,
            "sql": sql,
            "limit": limit,
        },
    )
    return r.json()


async def base_execute_app_schema(sql: str) -> dict:
    """API-Q2: 写操作（INSERT/UPDATE/DELETE）到应用 schema"""
    # 身份头 x-app-id / x-app-level 由基座 venv sitecustomize.py 自动注入，应用禁止手动设置
    # 本地开发（非基座环境）时 sitecustomize.py 不存在，通过 INJECT_IDENTITY_HEADERS 开关手动注入
    headers = (
        {"x-app-id": settings.APP_UUID, "x-app-level": settings.APP_LEVEL}
        if settings.INJECT_IDENTITY_HEADERS
        else None
    )
    r = await _get_client().post(
        _base_execute_url(),
        json={
            "datasourceId": settings.APP_DATASOURCE_ID,
            "schema": settings.APP_SCHEMA,
            "sql": sql,
        },
        headers=headers,
    )
    return r.json()


async def base_query_business(sql: str, limit: int = 100) -> dict:
    """API-Q1: 查询业务库（只读，按业务库组名 datasourceName）"""
    if not settings.BUSINESS_DATASOURCE_NAME:
        raise RuntimeError("未注入 BUSINESS_DATASOURCE_NAME，请创建应用时指定业务数据库")
    r = await _get_client().post(
        settings.BASE_QUERY_URL,
        json={
            "datasourceName": settings.BUSINESS_DATASOURCE_NAME,
            "sql": sql,
            "limit": limit,
        },
    )
    return r.json()


async def base_find_table_datasource(table_name: str) -> dict:
    """API-Q5: 按表名反查所属业务数据源组"""
    r = await _get_client().get(_base_find_table_url(), params={"table": table_name})
    return r.json()


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
    except Exception as exc:
        raise DatabaseError(f"基座 API 请求失败：{exc}")
    if resp.get("code") != 0:
        raise DatabaseError(resp.get("message", "基座查询失败"))
    return resp.get("data", {}).get("rows", [])


async def execute_app_schema(sql: str) -> int:
    """写操作（INSERT/UPDATE/DELETE），返回 affectedRows。"""
    try:
        resp = await base_execute_app_schema(sql)
    except Exception as exc:
        raise DatabaseError(f"基座 API 请求失败：{exc}")
    if resp.get("code") != 0:
        raise DatabaseError(resp.get("message", "基座写操作失败"))
    return resp.get("data", {}).get("affectedRows", 0)


async def query_business(sql: str, limit: int = 100) -> list[dict]:
    """查询业务库（只读），返回 rows 列表。"""
    try:
        resp = await base_query_business(sql, limit)
    except Exception as exc:
        raise DatabaseError(f"基座 API 请求失败：{exc}")
    if resp.get("code") != 0:
        raise DatabaseError(resp.get("message", "基座查询失败"))
    return resp.get("data", {}).get("rows", [])
