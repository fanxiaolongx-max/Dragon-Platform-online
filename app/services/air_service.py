# -*- coding: utf-8 -*-
"""AI 月报存储与取数：月报文档拆成应用库的行，便于调试页和 Dragon Claw 直接增删改。

- t_report_template：一份月报一行。description = "ai-report:<uuid>" 作为类型标记和稳定身份；
  content = 月报骨架 JSON（报告月份、开头模板、整体风格对话与主题、章节及其格子顺序）。
- t_report_block：一个格子一行。block_key = 格子 id，block_no = 所在章节序号，block_title = 格子名，
  content_html = 本月生成的 HTML，chart_type = 'ai-cell'，chart_data = 格子其余内容 JSON（尺寸、对话、配方、结果）。
- t_report_config：提示词。section='prompt' + block_id = 格子提示词；section='style' + block_id 为空 = 月报整体风格提示词。
  其它 section 的配置行（例如以后加的参数）保存时不会被动到。

提示词以 t_report_config 为准：在调试页或对话里改了配置行，下次打开月报就生效。
"""
import calendar
import json
import re
import time
import uuid
from typing import Any

from app.core.exceptions import QueryValidationError
from app.db import detect_sql_dialect, execute_app_schema, query_app_schema, query_business
from app.services.agent_service import check_read_sql
from app.utils.sql_helper import format_sql_value as lit

KIND = "ai-report"
CELL_TYPE = "ai-cell"
MAX_DOC_CHARS = 30_000_000
DATA_LIMIT = 1000
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_ID = re.compile(r"^[-\w]{1,32}$")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(text: Any, fallback: Any) -> Any:
    try:
        value = json.loads(text) if text else fallback
        return value if isinstance(value, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("zh") or value.get("en") or "")
    return str(value or "")


def _report_id(value: Any) -> int:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        raise QueryValidationError("月报 id 无效")
    if number <= 0:
        raise QueryValidationError("月报 id 无效")
    return number


def _cell_title(cell: dict) -> str:
    html = str((cell.get("output") or {}).get("html") or "")
    match = re.search(r'class="kit-title">([^<]{1,80})<', html) or re.search(r'data-slot-title="([^"]{1,80})"', html)
    if match:
        return match.group(1).strip()
    prompt = re.sub(r"\s+", " ", str(cell.get("prompt") or "")).strip()
    return prompt[:60] or "（未设置提示词）"


# --------------------------------------------------------------------
# 读
# --------------------------------------------------------------------

async def _all_rows(sql: str) -> list[dict]:
    """内部月报数据按基座单页 1000 行限制分页，不能静默截断格子与配置。"""
    if not re.search(r"\bORDER\s+BY\b", sql, re.I):
        sql += " ORDER BY id"
    result, offset = [], 0
    while True:
        rows = await query_app_schema(f"{sql} LIMIT {DATA_LIMIT} OFFSET {offset}", limit=DATA_LIMIT)
        result.extend(rows)
        if len(rows) < DATA_LIMIT:
            return result
        offset += DATA_LIMIT


async def _report_row(report_id: int) -> dict:
    rows = await query_app_schema(
        f"SELECT * FROM t_report_template WHERE id = {report_id} AND description LIKE '{KIND}:%' LIMIT 1", limit=1)
    if not rows:
        raise QueryValidationError(f"AI 月报 {report_id} 不存在")
    return rows[0]


async def list_documents() -> list[dict]:
    rows = await _all_rows(
        f"SELECT id, name, content, updated_at FROM t_report_template WHERE description LIKE '{KIND}:%' ORDER BY updated_at DESC, id DESC")
    result = []
    for row in rows:
        content = _loads(row.get("content"), {})
        result.append({"id": str(row["id"]), "name": row.get("name") or "AI 月报",
                       "reportMonth": content.get("reportMonth", ""), "updatedAt": str(row.get("updated_at") or "")})
    return result


async def read_document(report_id: Any) -> dict:
    report_id = _report_id(report_id)
    row = await _report_row(report_id)
    content = _loads(row.get("content"), {})
    blocks = await _all_rows(
        f"SELECT * FROM t_report_block WHERE report_id = {report_id} AND chart_type = '{CELL_TYPE}' ORDER BY order_no, id")
    configs = await _all_rows(
        f"SELECT id, block_id, section, config_text FROM t_report_config WHERE report_id = {report_id}")
    prompts = {c["block_id"]: _loads(c.get("config_text"), {}).get("prompt") for c in configs if c.get("section") == "prompt" and c.get("block_id") is not None}
    style_row = next((c for c in configs if c.get("section") == "style" and c.get("block_id") is None), None)

    cells: dict[str, dict] = {}
    for block in blocks:
        cell = _loads(block.get("chart_data"), {})
        cell["id"] = block["block_key"]
        prompt = prompts.get(block["id"])
        if prompt is not None:
            cell["prompt"] = str(prompt)
        output = cell.get("output")
        if isinstance(output, dict):
            output["html"] = block.get("content_html") or ""
        cells[block["block_key"]] = cell

    chapters, placed = [], set()
    for chapter in content.get("chapters") or []:
        ids = [cid for cid in chapter.get("cells") or [] if cid in cells]
        placed.update(ids)
        chapters.append({**{k: v for k, v in chapter.items() if k != "cells"}, "cells": [cells[cid] for cid in ids]})
    # 在调试页或对话里直接新增、却没登记进骨架的格子，放到最后一个章节，不会丢。
    orphans = [cell for key, cell in cells.items() if key not in placed]
    if orphans:
        if not chapters:
            chapters.append({"id": "chapter-main", "title": {"zh": "整体情况", "en": "Overview"}, "cells": []})
        chapters[-1]["cells"].extend(orphans)

    style = content.get("style") if isinstance(content.get("style"), dict) else {}
    if style_row:
        style = {**style, "prompt": str(_loads(style_row.get("config_text"), {}).get("prompt") or style.get("prompt") or "")}
    return {"version": 1, "id": str(report_id), "name": row.get("name") or "AI 月报", "reportMonth": content.get("reportMonth", ""),
            "template": content.get("template") or {}, "style": style, "chapters": chapters,
            "updatedAt": str(row.get("updated_at") or "")}


# --------------------------------------------------------------------
# 写
# --------------------------------------------------------------------

def _split(doc: dict) -> tuple[dict, list[dict], str]:
    """文档 → (骨架 content, 格子列表[带 chapter 序号], 整体风格提示词)"""
    if not isinstance(doc, dict) or not isinstance(doc.get("chapters"), list):
        raise QueryValidationError("月报内容无效")
    style = dict(doc.get("style") or {})
    style_prompt = str(style.pop("prompt", "") or "")
    chapters, cells = [], []
    for index, chapter in enumerate(doc["chapters"][:40]):
        if not isinstance(chapter, dict):
            continue
        ids = []
        for cell in (chapter.get("cells") or [])[:80]:
            if not isinstance(cell, dict) or not _ID.match(str(cell.get("id") or "")):
                raise QueryValidationError("格子 id 无效（只能是 1-32 位字母、数字、- 或 _）")
            ids.append(cell["id"])
            cells.append({"cell": cell, "chapter_no": index + 1})
        chapters.append({**{k: v for k, v in chapter.items() if k != "cells"}, "cells": ids})
    month = doc.get("reportMonth") if _MONTH.match(str(doc.get("reportMonth") or "")) else ""
    content = {"kind": KIND, "version": 1, "reportMonth": month, "template": doc.get("template") or {}, "style": style, "chapters": chapters}
    return content, cells, style_prompt


async def _upsert_config(existing: dict, report_id: int, block_id: Any, section: str, value: dict) -> None:
    text = _dumps(value)
    key = (block_id, section)
    row = existing.get(key)
    block_sql = "NULL" if block_id is None else str(int(block_id))
    if row:
        if row.get("config_text") != text:
            await execute_app_schema(f"UPDATE t_report_config SET config_text = {lit(text)}, updated_at = {lit(_now())} WHERE id = {row['id']}")
    else:
        await execute_app_schema(
            f"INSERT INTO t_report_config (report_id, block_id, section, config_text, created_at, updated_at) "
            f"VALUES ({report_id}, {block_sql}, {lit(section)}, {lit(text)}, {lit(_now())}, {lit(_now())})")


async def save_document(doc: dict) -> dict:
    await detect_sql_dialect()
    if len(_dumps(doc)) > MAX_DOC_CHARS:
        raise QueryValidationError("月报内容过大")
    content, cells, style_prompt = _split(doc)
    name = str(doc.get("name") or "AI 月报").strip()[:128] or "AI 月报"
    title = _text((doc.get("template") or {}).get("title"))[:255]
    now = _now()

    report_id = None
    if str(doc.get("id") or "").isdigit():
        rows = await query_app_schema(
            f"SELECT id FROM t_report_template WHERE id = {int(doc['id'])} AND description LIKE '{KIND}:%' LIMIT 1", limit=1)
        report_id = rows[0]["id"] if rows else None
    if report_id:
        await execute_app_schema(
            f"UPDATE t_report_template SET name = {lit(name)}, title = {lit(title)}, content = {lit(_dumps(content))}, "
            f"updated_at = {lit(now)} WHERE id = {report_id}")
    else:
        marker = f"{KIND}:{uuid.uuid4().hex}"
        await execute_app_schema(
            "INSERT INTO t_report_template (name, title, description, content, status, created_at, updated_at) "
            f"VALUES ({lit(name)}, {lit(title)}, {lit(marker)}, {lit(_dumps(content))}, 'draft', {lit(now)}, {lit(now)})")
        rows = await query_app_schema(f"SELECT id FROM t_report_template WHERE description = {lit(marker)} LIMIT 1", limit=1)
        if not rows:
            raise QueryValidationError("月报保存后未能读回，请检查应用库写入权限")
        report_id = rows[0]["id"]

    # 格子：只更新有变化的行，新增缺少的，删除已经不在月报里的。
    existing = {b["block_key"]: b for b in await _all_rows(
        f"SELECT * FROM t_report_block WHERE report_id = {report_id} AND chart_type = '{CELL_TYPE}'")}
    wanted = set()
    for order, item in enumerate(cells):
        cell = dict(item["cell"])
        key = cell["id"]
        wanted.add(key)
        output = dict(cell.get("output") or {}) if isinstance(cell.get("output"), dict) else None
        html = (output or {}).pop("html", "") or ""
        data = {k: v for k, v in cell.items() if k not in ("id", "prompt", "output")}
        if output is not None:
            data["output"] = output
        row = {"block_no": str(item["chapter_no"]), "block_title": _cell_title(cell)[:255], "content_html": html,
               "chart_data": _dumps(data), "order_no": order}
        old = existing.get(key)
        if old:
            changed = {k: v for k, v in row.items() if str(old.get(k) if old.get(k) is not None else "") != str(v)}
            if changed:
                sets = ", ".join(f"{k} = {lit(v)}" for k, v in changed.items())
                await execute_app_schema(f"UPDATE t_report_block SET {sets}, updated_at = {lit(now)} WHERE id = {old['id']}")
        else:
            cols = {"report_id": report_id, "block_key": key, "chart_type": CELL_TYPE, **row, "created_at": now, "updated_at": now}
            await execute_app_schema(f"INSERT INTO t_report_block ({', '.join(cols)}) VALUES ({', '.join(lit(v) for v in cols.values())})")
    for key, old in existing.items():
        if key not in wanted:
            await execute_app_schema(f"DELETE FROM t_report_config WHERE report_id = {report_id} AND block_id = {old['id']}")
            await execute_app_schema(f"DELETE FROM t_report_block WHERE id = {old['id']}")

    # 提示词写进配置表。
    ids = {b["block_key"]: b["id"] for b in await _all_rows(
        f"SELECT id, block_key FROM t_report_block WHERE report_id = {report_id} AND chart_type = '{CELL_TYPE}'")}
    configs = {(c["block_id"], c["section"]): c for c in await _all_rows(
        f"SELECT id, block_id, section, config_text FROM t_report_config WHERE report_id = {report_id}")}
    for item in cells:
        block_id = ids.get(item["cell"]["id"])
        if block_id is not None:
            await _upsert_config(configs, report_id, block_id, "prompt", {"prompt": str(item["cell"].get("prompt") or "")})
    await _upsert_config(configs, report_id, None, "style", {"prompt": style_prompt})
    return await read_document(report_id)


async def delete_document(report_id: Any) -> dict:
    report_id = _report_id(report_id)
    await _report_row(report_id)
    await execute_app_schema(f"DELETE FROM t_report_config WHERE report_id = {report_id}")
    await execute_app_schema(f"DELETE FROM t_report_block WHERE report_id = {report_id}")
    await execute_app_schema(f"DELETE FROM t_report_template WHERE id = {report_id}")
    return {"deleted": True}


# --------------------------------------------------------------------
# 格子级编辑（调试页 / Dragon Claw 使用）：读出整份月报、改一处、整体保存，保证骨架和行一致
# --------------------------------------------------------------------

def _find_cell(doc: dict, cell_id: str) -> tuple[dict, int] | tuple[None, None]:
    for chapter in doc["chapters"]:
        for index, cell in enumerate(chapter["cells"]):
            if cell.get("id") == cell_id:
                return chapter, index
    return None, None


def outline(doc: dict) -> dict:
    return {"id": doc["id"], "name": doc["name"], "reportMonth": doc["reportMonth"],
            "stylePrompt": (doc.get("style") or {}).get("prompt", ""),
            "chapters": [{"id": ch.get("id"), "title": _text(ch.get("title")),
                          "cells": [{"id": c.get("id"), "title": _cell_title(c), "span": c.get("span", 6), "prompt": c.get("prompt", ""),
                                     "generated": bool(c.get("recipe"))} for c in ch["cells"]]} for ch in doc["chapters"]]}


async def upsert_cell(report_id: Any, cell_id: str | None = None, chapter_id: str | None = None, prompt: str | None = None,
                      span: int | None = None, height: int | None = None) -> dict:
    doc = await read_document(report_id)
    if cell_id:
        chapter, index = _find_cell(doc, cell_id)
        if chapter is None:
            raise QueryValidationError(f"格子 {cell_id} 不存在")
        cell = chapter["cells"][index]
    else:
        chapter = next((ch for ch in doc["chapters"] if ch.get("id") == chapter_id), None) if chapter_id else (doc["chapters"][-1] if doc["chapters"] else None)
        if chapter is None:
            if chapter_id:
                raise QueryValidationError(f"章节 {chapter_id} 不存在")
            chapter = {"id": "chapter-" + uuid.uuid4().hex[:10], "title": {"zh": "整体情况", "en": "Overview"}, "cells": []}
            doc["chapters"].append(chapter)
        cell = {"id": "cell-" + uuid.uuid4().hex[:12], "span": 6, "prompt": "", "chat": []}
        chapter["cells"].append(cell)
    if prompt is not None:
        prompt = str(prompt)[:4000]
        if prompt != cell.get("prompt"):
            cell["prompt"] = prompt
            # 提示词换了，旧配方不再对应；保留旧结果显示，打开月报后点“试一下”或在格子对话里重新生成。
            cell.setdefault("chat", []).append({"role": "ai", "kind": "prompt", "text": prompt, "edited": True})
    if span is not None:
        cell["span"] = max(1, min(12, int(span)))
    if height is not None:
        cell["height"] = max(0, min(1600, int(height)))
    saved = await save_document(doc)
    return {"report_id": saved["id"], "cell_id": cell["id"], "outline": outline(saved)}


async def delete_cell(report_id: Any, cell_id: str) -> dict:
    doc = await read_document(report_id)
    chapter, index = _find_cell(doc, cell_id)
    if chapter is None:
        raise QueryValidationError(f"格子 {cell_id} 不存在")
    removed = chapter["cells"].pop(index)
    saved = await save_document(doc)
    return {"report_id": saved["id"], "deleted": {"id": removed.get("id"), "prompt": removed.get("prompt", "")}, "outline": outline(saved)}


async def set_style_prompt(report_id: Any, prompt: str) -> dict:
    doc = await read_document(report_id)
    doc.setdefault("style", {})["prompt"] = str(prompt)[:4000]
    saved = await save_document(doc)
    return {"report_id": saved["id"], "stylePrompt": saved["style"].get("prompt", "")}


# --------------------------------------------------------------------
# 配方取数：SQL 来源按报告月份替换占位符后只读执行
# --------------------------------------------------------------------

def _shift(month: str, offset: int) -> tuple[int, int]:
    year, number = map(int, month.split("-"))
    total = year * 12 + number - 1 + offset
    return total // 12, total % 12 + 1


def month_values(month: str, offset: int = 0) -> dict:
    if not _MONTH.match(str(month or "")):
        raise QueryValidationError("报告月份应为 YYYY-MM")
    year, number = _shift(month, offset)
    nyear, nnumber = _shift(month, offset + 1)
    pyear, pnumber = _shift(month, offset - 1)
    last = calendar.monthrange(year, number)[1]
    return {"month": f"{year}-{number:02d}", "month_start": f"{year}-{number:02d}-01", "month_end": f"{year}-{number:02d}-{last:02d}",
            "next_month_start": f"{nyear}-{nnumber:02d}-01", "prev_month": f"{pyear}-{pnumber:02d}", "yyyymm": f"{year}{number:02d}",
            "year": str(year), "month_num": str(number)}


def resolve_sql(sql: str, month: str, offset: int = 0) -> str:
    values = month_values(month, offset)

    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in values:
            raise QueryValidationError(f"未知占位符 {{{{{key}}}}}，可用：{', '.join('{{' + k + '}}' for k in values)}")
        return values[key]
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replace, str(sql or ""))


async def run_data(month: str, recipe: dict) -> dict:
    if not _MONTH.match(str(month or "")):
        raise QueryValidationError("报告月份无效")
    sources = (recipe or {}).get("sources") or []
    result, missing = {}, []
    for source in sources[:8]:
        if not isinstance(source, dict):
            continue
        sid, kind, label = str(source.get("id") or ""), source.get("kind"), str(source.get("label") or "")
        if kind == "report":
            continue  # 月报自身的大纲 / 其他格子结果由页面填充
        if kind != "sql":
            result[sid] = None
            missing.append({"id": sid, "label": label, "error": f"不支持的数据来源类型 {kind}"})
            continue
        offset = max(-24, min(0, int(source.get("monthOffset") or 0)))
        try:
            sql = check_read_sql(resolve_sql(source.get("sql"), month, offset))
            db = "app" if source.get("source") == "app" else "netcare"
            rows = await (query_app_schema if db == "app" else query_business)(sql, limit=DATA_LIMIT)
            headers = list(rows[0].keys()) if rows else []
            result[sid] = {"month": month_values(month, offset)["month"], "source": db, "label": label, "sql": sql,
                           "headers": headers, "rows": rows, "truncated": len(rows) >= DATA_LIMIT}
        except Exception as exc:
            result[sid] = None
            missing.append({"id": sid, "label": label, "error": str(getattr(exc, "message", exc))[:300]})
    return {"input": result, "missing": missing}
