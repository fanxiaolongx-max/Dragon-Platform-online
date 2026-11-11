# -*- coding: utf-8 -*-
"""交互日志、表失败标记、业务表清单快照。

记录应用和外部的每次交互，出问题时可以回溯：
- 基座 API 请求（业务库 / 应用库 / 元数据），由 db.request_listeners 在每次请求最终结果后通知；
- 浏览器上报的 ADC 内嵌对话（提问、回答、耗时、错误），经 POST /api/ops/logs；
- 业务表清单刷新（GET /data/tables 的最新表名，与上次相比新增 / 减少了哪些表）。

存储复用既有的 t_report_config（不新增表、运行期不发 DDL，与 AIR 一致）：report_id = 0 保留给本模块，
section 区分用途：ops_log 每条日志一行；ops_tbl_health 一行 JSON 记录查询失败的表；ops_tbl_snap 一行 JSON
记录最近一次业务表清单。日志在内存里缓冲，约 2 秒批量写入一次（单条多行 INSERT），写日志本身不再记日志。
"""
import asyncio
import json
import re
import time
from contextvars import ContextVar
from typing import Any

from app import db
from app.core.diagnostic_safety import clean
from app.core.logger import logger
from app.utils.sql_helper import format_sql_value as lit

REPORT_ID = 0
LOG_SECTION, HEALTH_SECTION, SNAP_SECTION = "ops_log", "ops_tbl_health", "ops_tbl_snap"
KINDS = ("db", "adc", "model", "ai", "tables", "api", "ui")
CLIENT_KINDS = ("adc", "model", "ai", "ui")
RETAIN_DAYS = 30
FLUSH_DELAY = 2.0
BUFFER_MAX = 2000
TEXT_MAX = 4000
SQL_MAX = 2000
REFRESH_REUSE = 60  # 秒：两个页面同时打开时只刷新一次业务表清单

_suppress = ContextVar("ops_suppress", default=False)
request_context = ContextVar("ops_request_context", default=None)

_buffer: list[dict] = []
_flush_task: asyncio.Task | None = None
_last_prune = 0.0
_health: dict[str, dict] = {}
_health_touched: dict[str, dict | None] = {}
_health_loaded = False
_health_dirty = False
_snapshot: dict | None = None
_snapshot_checked = 0.0
_refresh_lock = asyncio.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _loads(text: Any, fallback: Any) -> Any:
    try:
        value = json.loads(text) if isinstance(text, str) and text else fallback
        return value if isinstance(value, type(fallback)) else fallback
    except ValueError:
        return fallback


def clip(value: Any, limit: int = TEXT_MAX) -> str:
    text = value if isinstance(value, str) else _dumps(value)
    return text if len(text) <= limit else f"{text[:limit]}…（共 {len(text)} 字，已截断）"


def page_of(referer: str, explicit: str = "") -> str:
    """请求来自哪个页面：开发者页（dev）还是 AI 月报（air）。"""
    if explicit in ("dev", "air"):
        return explicit
    path = re.sub(r"[?#].*$", "", referer or "")
    if re.search(r"/(dev|api-test)(\.html)?$", path):
        return "dev"
    return "air" if path else ""


# --------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------

def record(kind: str, title: str, status: str = "ok", detail: dict | None = None, ms: int | None = None, page: str = "") -> dict:
    ctx = request_context.get() or {}
    entry = {"at": _now(), "kind": kind if kind in KINDS else "ui", "status": "error" if status == "error" else "ok",
             "page": page or ctx.get("page", ""), "route": ctx.get("route", ""), "title": clip(title, 300),
             "ms": ms, "detail": detail or {}}
    if len(_buffer) < BUFFER_MAX:
        _buffer.append(entry)
    _schedule()
    return entry


def _schedule() -> None:
    global _flush_task
    try:
        loop = asyncio.get_running_loop()
        if _flush_task and not _flush_task.done() and _flush_task.get_loop() is loop:
            return
        _flush_task = loop.create_task(_delayed_flush())
    except RuntimeError:
        pass  # 没有事件循环（同步测试或启动前），下次请求再写


async def _delayed_flush() -> None:
    await asyncio.sleep(FLUSH_DELAY)
    await flush()


def _is_missing_table_error(exc: Exception) -> bool:
    return bool(re.search(r"no such table|doesn't exist|does not exist", str(exc), re.I))


async def flush() -> None:
    """把缓冲的日志和表失败标记写进应用库；失败只记服务端日志，不影响业务请求。"""
    global _buffer, _health_dirty, _last_prune
    token = _suppress.set(True)
    missing_table = False
    try:
        entries, _buffer = _buffer, []
        now = _now()
        for start in range(0, len(entries), 20):
            chunk = entries[start:start + 20]
            values = ",".join(f"({REPORT_ID}, NULL, '{LOG_SECTION}', {lit(_dumps(e))}, {lit(e['at'])}, {lit(now)})" for e in chunk)
            try:
                await db.execute_app_schema(
                    f"INSERT INTO t_report_config (report_id, block_id, section, config_text, created_at, updated_at) VALUES {values}")
            except Exception as exc:
                if _is_missing_table_error(exc):
                    missing_table = True
                    logger.warning(f"交互日志写入跳过（应用表尚未初始化，丢弃 {len(entries) - start} 条）：{exc}")
                    break
                # 整批失败时逐条重写，一条写不进去（超长、特殊字符）不连累同批的其它日志
                logger.warning(f"交互日志批量写入失败，改为逐条写入（{len(chunk)} 条）：{exc}")
                for e in chunk:
                    try:
                        await db.execute_app_schema(
                            "INSERT INTO t_report_config (report_id, block_id, section, config_text, created_at, updated_at) "
                            f"VALUES ({REPORT_ID}, NULL, '{LOG_SECTION}', {lit(_dumps(e))}, {lit(e['at'])}, {lit(now)})")
                    except Exception as one:
                        logger.warning(f"交互日志写入失败（丢弃 1 条：{e.get('title', '')[:60]}）：{one}")
        if _health_dirty and not missing_table:
            try:
                await _ensure_health()
                await _save_row(HEALTH_SECTION, _health)
                _health_dirty = False
            except Exception as exc:
                if _is_missing_table_error(exc):
                    missing_table = True
                logger.warning(f"表失败标记写入失败：{exc}")
        if not missing_table and time.time() - _last_prune > 3600:
            _last_prune = time.time()
            cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - RETAIN_DAYS * 86400))
            try:
                await db.execute_app_schema(
                    f"DELETE FROM t_report_config WHERE report_id = {REPORT_ID} AND section = '{LOG_SECTION}' AND created_at < {lit(cutoff)}")
            except Exception as exc:
                logger.warning(f"清理 {RETAIN_DAYS} 天前的交互日志失败：{exc}")
    finally:
        _suppress.reset(token)


async def _load_row(section: str) -> tuple[int | None, Any]:
    rows = await db.query_app_schema(
        f"SELECT id, config_text FROM t_report_config WHERE report_id = {REPORT_ID} AND section = '{section}' ORDER BY id DESC LIMIT 1", limit=1)
    return (rows[0]["id"], _loads(rows[0].get("config_text"), {})) if rows else (None, {})


async def _save_row(section: str, value: Any) -> None:
    row_id, _ = await _load_row(section)
    text, now = lit(_dumps(value)), lit(_now())
    if row_id is None:
        await db.execute_app_schema(
            "INSERT INTO t_report_config (report_id, block_id, section, config_text, created_at, updated_at) "
            f"VALUES ({REPORT_ID}, NULL, '{section}', {text}, {now}, {now})")
    else:
        await db.execute_app_schema(f"UPDATE t_report_config SET config_text = {text}, updated_at = {now} WHERE id = {int(row_id)}")


# --------------------------------------------------------------------
# 基座请求 → 日志 + 表失败标记
# --------------------------------------------------------------------

_TABLE_RE = re.compile(r"\b(?:FROM|JOIN)\s+((?:`[^`]+`|\w+)(?:\s*\.\s*(?:`[^`]+`|\w+))?)", re.I)
_CTE_RE = re.compile(r"(?:\bWITH\s+(?:RECURSIVE\s+)?|,\s*)(\w+)\s+AS\s*\(", re.I)


def tables_in(sql: str) -> list[str]:
    """SQL 里 FROM / JOIN 的业务表名（小写、去掉库名前缀）；跳过 information_schema 和 WITH 定义的临时名。"""
    ctes = {name.lower() for name in _CTE_RE.findall(sql or "")}
    found = []
    for ref in _TABLE_RE.findall(sql or ""):
        parts = [part.strip().strip("`").lower() for part in ref.split(".")]
        if len(parts) == 2 and parts[0] == "information_schema":
            continue
        name = parts[-1]
        if name and name not in ctes and name not in found:
            found.append(name)
    return found


def _table_level_failure(event: dict, message: str) -> bool:
    """只有查询本身的报错才给表打失败标记；网络、限流、鉴权、网关、数据源配置这类整体故障不算到某张表头上。"""
    error = event.get("error")
    data = getattr(error, "data", None) if error else None
    status = data.get("httpStatus") if isinstance(data, dict) else None
    if error is not None and not isinstance(error, db.DatabaseError):
        return False
    if getattr(error, "code", None) == 429 or status in (401, 403, 429, 502, 503, 504):
        return False
    return "数据源不存在" not in message and "BUSINESS_DATASOURCE_NAME" not in message


def mark_table(table: str, ok: bool, message: str = "") -> None:
    global _health_dirty
    table = table.strip().lower()
    if not table:
        return
    if ok:
        if table in _health or (not _health_loaded and table not in _health_touched):
            _health.pop(table, None)
            _health_touched[table] = None
            _health_dirty = True
        return
    entry = dict(_health.get(table) or {})
    entry.update(fails=int(entry.get("fails") or 0) + 1, lastFail=_now(), lastError=clip(message, 300))
    _health[table] = entry
    _health_touched[table] = entry
    _health_dirty = True


async def _ensure_health() -> None:
    global _health, _health_loaded
    if _health_loaded:
        return
    token = _suppress.set(True)
    try:
        _, stored = await _load_row(HEALTH_SECTION)
    finally:
        _suppress.reset(token)
    merged = {k: v for k, v in stored.items() if isinstance(v, dict)}
    for table, entry in _health_touched.items():
        if entry is None:
            merged.pop(table, None)
        else:
            previous = merged.get(table) or {}
            merged[table] = {**entry, "fails": int(previous.get("fails") or 0) + int(entry.get("fails") or 0) if previous else entry.get("fails")}
    _health, _health_loaded = merged, True


async def table_health() -> dict:
    try:
        await _ensure_health()
    except Exception as exc:
        logger.warning(f"读取表失败标记失败：{exc}")
    return dict(_health)


def on_base_request(event: dict) -> None:
    if _suppress.get():
        return
    payload, data, error = event.get("payload") or {}, event.get("data"), event.get("error")
    scope = "app" if "schema" in payload else "business" if "datasourceName" in payload else "metadata"
    sql = str(payload.get("sql") or "")
    code = data.get("code") if isinstance(data, dict) else None
    failed = error is not None or code not in (0, "0", None)
    message = clean(error) if error is not None else clean(data.get("message")) if failed and isinstance(data, dict) else ""
    rows = None
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        inner = data["data"]
        rows = len(inner["rows"]) if isinstance(inner.get("rows"), list) else inner.get("affectedRows")
    tables = tables_in(sql) if scope == "business" else []
    write = event.get("path", "").endswith("/execute")
    action = {"app": "应用库写入" if write else "应用库查询", "business": "业务库查询"}.get(scope, "基座元数据")
    title = f"{action}{' · ' + '、'.join(tables[:3]) if tables else ''}{' 失败' if failed else ''}"
    err_data = getattr(error, "data", None) if error is not None else None
    detail = {"method": event.get("method"), "endpoint": clean(event.get("path")), "scope": scope,
              "datasource": clean(payload.get("datasourceName") or payload.get("datasourceId") or ""),
              "sql": clip(sql, SQL_MAX), "limit": payload.get("limit"), "params": event.get("params") or None,
              "tables": tables, "rows": rows}
    if failed:
        detail.update(error=message, code=clean(code) if code is not None else getattr(error, "code", None),
                      httpStatus=err_data.get("httpStatus") if isinstance(err_data, dict) else None,
                      requestId=err_data.get("requestId") if isinstance(err_data, dict) else None)
    record("db", title, "error" if failed else "ok", {k: v for k, v in detail.items() if v not in (None, "", [])}, event.get("ms"))
    if tables and (not failed or _table_level_failure(event, message)):
        for table in tables:
            mark_table(table, not failed, message)


def install() -> None:
    if on_base_request not in db.request_listeners:
        db.request_listeners.append(on_base_request)


# --------------------------------------------------------------------
# 浏览器上报（ADC 对话等）
# --------------------------------------------------------------------

def _client_time(value: Any) -> str:
    """浏览器发生时间（重试上报时与服务端收到时间不同）；只接受两天内的合理时间。"""
    try:
        from datetime import datetime
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if abs(time.time() - ts) < 2 * 86400 else ""


def record_client(entries: Any, page: str = "") -> int:
    count = 0
    for item in (entries if isinstance(entries, list) else [])[:50]:
        if not isinstance(item, dict):
            continue
        detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
        detail = {str(k)[:40]: v if not isinstance(v, str) and len(_dumps(v)) <= TEXT_MAX else clip(v)
                  for k, v in list(detail.items())[:30]}
        ms = item.get("ms")
        entry = record(item.get("kind") if item.get("kind") in CLIENT_KINDS else "ui", str(item.get("title") or "前端事件"),
                       "error" if item.get("status") == "error" else "ok", detail,
                       int(ms) if isinstance(ms, (int, float)) else None, page_of("", str(item.get("page") or page)))
        at = _client_time(item.get("clientAt"))
        if at:
            entry["at"] = at
        count += 1
    return count


# --------------------------------------------------------------------
# 查询日志
# --------------------------------------------------------------------

async def list_logs(limit: int = 200, days: float = 0, kind: str = "", status: str = "", q: str = "") -> dict:
    await flush()
    limit = max(1, min(1000, int(limit or 200)))
    where = [f"report_id = {REPORT_ID}", f"section = '{LOG_SECTION}'"]
    if days and days > 0:
        where.append(f"created_at >= {lit(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - float(days) * 86400)))}")
    if kind in KINDS:
        where.append("config_text LIKE " + lit('%"kind":"' + kind + '"%'))
    if status in ("ok", "error"):
        where.append("config_text LIKE " + lit('%"status":"' + status + '"%'))
    keyword = re.sub(r"[%_\\]", "", str(q or "").strip())[:100]
    if keyword:
        where.append(f"config_text LIKE {lit('%' + keyword + '%')}")
    token = _suppress.set(True)
    try:
        rows = await db.query_app_schema(
            f"SELECT id, config_text FROM t_report_config WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT {limit}", limit=limit)
    finally:
        _suppress.reset(token)
    logs = [{"id": row["id"], **_loads(row.get("config_text"), {})} for row in rows]
    return {"logs": logs, "limit": limit, "days": days, "retainDays": RETAIN_DAYS}


# --------------------------------------------------------------------
# 业务表清单快照（GET /data/tables 的最新表名）
# --------------------------------------------------------------------

async def _ensure_snapshot() -> dict:
    global _snapshot
    if _snapshot is None:
        token = _suppress.set(True)
        try:
            _, _snapshot = await _load_row(SNAP_SECTION)
        except Exception as exc:
            logger.warning(f"读取业务表清单快照失败：{exc}")
            return {}
        finally:
            _suppress.reset(token)
    return _snapshot or {}


async def live_tables() -> set[str]:
    snap = await _ensure_snapshot()
    return {str(t.get("t", "")).lower() for t in snap.get("tables") or [] if isinstance(t, dict)}


async def snapshot() -> dict:
    snap = await _ensure_snapshot()
    return {"snapshot": snap or None, "health": await table_health()}


async def refresh_tables(page: str = "", force: bool = False) -> dict:
    """查一次 GET /data/tables 的最新表名，和上次比新增 / 减少了哪些表，写快照并记一条醒目的日志。"""
    global _snapshot, _snapshot_checked
    from app.services.data_service import DataService
    async with _refresh_lock:
        previous = await _ensure_snapshot()
        if not force and previous and time.time() - _snapshot_checked < REFRESH_REUSE:
            return {**previous, "reused": True, "health": await table_health()}
        started = time.monotonic()
        try:
            tables = await DataService().list_tables("netcare")
        except Exception as exc:
            record("tables", "业务表清单刷新失败", "error", {"error": clean(exc), "previousTotal": len(previous.get("tables") or [])},
                   round((time.monotonic() - started) * 1000), page)
            raise
        current = [{"t": t["table_name"], "cn": t.get("table_comment") or ""} for t in tables]
        before = {str(t.get("t")).lower(): t for t in previous.get("tables") or [] if isinstance(t, dict)}
        now_map = {t["t"].lower(): t for t in current}
        first = not before
        added = [] if first else [t for key, t in now_map.items() if key not in before]
        removed = [] if first else [t for key, t in before.items() if key not in now_map]
        snap = {"at": _now(), "total": len(current), "tables": current, "added": added, "removed": removed,
                "previousAt": previous.get("at"), "previousTotal": len(before), "first": first}
        ms = round((time.monotonic() - started) * 1000)
        if first:
            title = f"业务表清单首次记录：共 {len(current)} 张表"
        else:
            title = f"业务表清单刷新：共 {len(current)} 张（上次 {len(before)} 张），新增 {len(added)} 张，减少 {len(removed)} 张"
        record("tables", title, "ok", {"total": len(current), "previousTotal": len(before), "previousAt": previous.get("at"),
                                       "first": first, "added": added, "removed": removed}, ms, page)
        token = _suppress.set(True)
        try:
            await _save_row(SNAP_SECTION, snap)
        except Exception as exc:
            logger.warning(f"保存业务表清单快照失败：{exc}")
        finally:
            _suppress.reset(token)
        _snapshot, _snapshot_checked = snap, time.time()
        return {**snap, "reused": False, "health": await table_health()}
