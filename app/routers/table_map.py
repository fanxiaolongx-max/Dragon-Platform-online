# -*- coding: utf-8 -*-
"""表映射路由 — 索引目录模块 / 源表 ↔ 业务库落地表

数据来自 static/data/table_map.json（《运营指标-索引目录》《运营工作台-高斯底表》整理）。
源表在上游库（sdisd/dwritr 等）不在业务库，"源表直查"自动改查对应落地表。
"""
import json
import os
import re
from typing import List

from fastapi import APIRouter, Query

from app.config import settings
from app.core.response import success, error
from app.db import query_business, query_app_schema

router = APIRouter(prefix="/data/table-map", tags=["data-map"])

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_MAP_PATH = os.path.join(_ROOT, "static", "data", "table_map.json")
_BIZ_JSON_PATH = os.path.join(_ROOT, "business_tables.json")
_CATALOG_PATH = os.path.join(_ROOT, "static", "data", "all_tables.json")

# 应用 schema（月报存储）表 —— 与 db/init.sql 保持一致；不在业务库 netcare 中
APP_TABLES = ("t_report_template", "t_report_block", "t_data_element", "t_data_source", "t_report_config")

_PAGE = 1000       # 基座 API 单页上限
_MAX_ROWS = 50000  # "不限行数"安全上限
_OPS = ("=", "!=", ">", "<", ">=", "<=", "like", "not like", "in")


def _load_map() -> dict:
    with open(_MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_biz_tables() -> list:
    """读取业务库表清单底稿 business_tables.json（sheet/module/sub_module/table_type）。"""
    if not os.path.exists(_BIZ_JSON_PATH):
        return []
    with open(_BIZ_JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


_catalog_cache: dict | None = None


def _load_catalog() -> dict:
    """全表目录 static/data/all_tables.json（db/build_all_tables.py 生成，441 表）。

    返回 {base: {t, cn, mod, cate, grain, rows, empty}}；文件缺失时返回空 dict。
    """
    global _catalog_cache
    if _catalog_cache is None:
        _catalog_cache = {}
        if os.path.exists(_CATALOG_PATH):
            with open(_CATALOG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            for e in data.get("tables", []):
                _catalog_cache[_base_name(e.get("t", ""))] = e
    return _catalog_cache


def _catalog_mod(table: str) -> dict:
    """目录内表（映射外）合成的"假模块"，供 _lookup_payload 使用。"""
    e = _load_catalog().get(table.lower())
    if not e:
        return {}
    return {
        "name": e.get("mod") or "全表目录",
        "remark": ("业务库 netcare 全量表（目录内置）· " + (e.get("cn") or e.get("t")))
                  + (" · 空表" if e.get("empty") else f" · 约 {e.get('rows') or 0} 行"),
        "source_tables": [],
        "landing_tables": [table],
    }


def _base_name(name: str) -> str:
    """归一表名：去掉 schema 前缀、转小写。无 schema 前缀时保持原样小写。"""
    base = name.strip().lower().split(".")[-1]
    return base


def _biz_index() -> dict:
    """base(小写) -> {module, sub_module, table_type}，供清单与体检匹配。"""
    idx = {}
    for b in _load_biz_tables():
        t = str(b.get("table_name", "")).strip()
        if not t:
            continue
        idx.setdefault(_base_name(t), {
            "module": b.get("module", "") or "",
            "sub_module": b.get("sub_module", "") or "",
            "table_type": b.get("table_type", "") or "",
        })
    return idx


def _resolve(name: str):
    """按表名（源表/落地表，可带 schema 前缀）解析所属模块。

    返回 (module_dict, resolved_landing_table, is_source)；未命中返回 (None, None, None)。
    源表 → 改查该模块第一张落地表；落地表 → 精确解析到被输入的那张表。
    """
    key = name.strip().lower()
    base = key.split(".")[-1]
    for mod in _load_map()["modules"]:
        sources = {s.lower() for s in mod["source_tables"]}
        if key in sources or base in sources:
            landing = mod["landing_tables"][0] if mod["landing_tables"] else None
            return mod, landing, True
        for t in mod["landing_tables"]:
            tl = t.lower()
            if key == tl or tl.split(".")[-1] == base:
                return mod, t, False
    return None, None, None


def _lookup_payload(name: str, mod: dict, landing: str, is_source: bool) -> dict:
    return {
        "name": name,
        "module": mod["name"],
        "remark": mod.get("remark", ""),
        "is_source": is_source,
        "source_tables": mod["source_tables"],
        "landing_tables": mod["landing_tables"],
        "resolved_table": landing,
    }


@router.get("")
def get_table_map():
    """完整映射：22 个索引目录模块 + 源表 + 业务库落地表"""
    return success(data=_load_map())


@router.get("/all-tables")
def list_all_db_tables():
    """全表目录（业务库 netcare 441 表）：中文名/模块/类别/粒度/行数/空表标记，有数据靠前、空表靠后。

    静态文件 static/data/all_tables.json，由 db/build_all_tables.py 重新生成。
    """
    data = {"total": 0, "empty_count": 0, "mod_order": [], "tables": []}
    if os.path.exists(_CATALOG_PATH):
        with open(_CATALOG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    return success(data=data)


@router.get("/lookup")
def lookup_table(name: str = Query(..., description="源表名或落地表名，可带 schema 前缀")):
    """解析单个表名 -> 所属模块 / 源表 / 落地表（映射外表回退全表目录直查）"""
    mod, landing, is_source = _resolve(name)
    if mod is None:
        base = _base_name(name)
        if base in _load_catalog():
            mod, landing, is_source = _catalog_mod(base), base, False
        else:
            return error(code=404, message=f"映射中未找到表名：{name}")
    return success(data=_lookup_payload(name, mod, landing, is_source))


def _quote(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


def _flt_where(flt: List[str]):
    """解析过滤条件 '列名|运算符|值'（多条 AND）。返回 (where_sql, err_msg)。"""
    if not flt:
        return "", None
    conds = []
    for f in flt:
        parts = f.split("|", 2)
        if len(parts) != 3 or not all(parts):
            return None, f"过滤条件格式应为 列名|运算符|值，收到：{f}"
        col = re.sub(r"[^0-9A-Za-z_]", "", parts[0])
        op = parts[1].strip().lower()
        val = parts[2].strip()
        if not col:
            return None, f"过滤列名非法：{f}"
        if op not in _OPS:
            return None, f"不支持的运算符：{op}（支持 {', '.join(_OPS)}）"
        if not val:
            return None, f"过滤值不能为空：{f}"
        if op == "in":
            vals = [_quote(v) for v in val.split(",") if v.strip()]
            if not vals:
                return None, f"IN 过滤值不能为空：{f}"
            conds.append(f"`{col}` IN ({','.join(vals)})")
        else:
            conds.append(f"`{col}` {op} {_quote(val)}")
    return " WHERE " + " AND ".join(conds), None


@router.get("/data")
async def query_by_table(
    name: str = Query(..., description="源表名或落地表名"),
    limit: int = Query(100, ge=0, le=_MAX_ROWS, description="返回行数，0 = 不限（自动分页，上限 5 万行）"),
    flt: List[str] = Query([], description="过滤条件 列名|运算符|值，可传多个（AND）；运算符 = != > < >= <= like not like in"),
    cols: str = Query("", description="只返回指定列，逗号分隔；空 = 全部列"),
):
    """直接查表数据：源表自动改查业务库落地表（第一张），落地表直查；支持行过滤与列选择。

    映射外的表名回退全表目录（all_tables.json）：业务库 441 张表均可直查（空表返回 0 行）。
    """
    mod, landing, is_source = _resolve(name)
    if mod is None:
        base = _base_name(name)
        if base in _load_catalog():
            mod, landing, is_source = _catalog_mod(base), base, False
        else:
            return error(code=404, message=f"映射中未找到表名：{name}")
    if not landing:
        return error(code=400, message=f"模块[{mod['name']}]在业务库无落地表，无法直查。{mod.get('remark', '')}")
    table = re.sub(r"[^0-9A-Za-z_]", "", landing)
    if not table:
        return error(code=400, message="落地表名非法")

    where, werr = _flt_where(flt)
    if werr:
        return error(code=400, message=werr)

    col_names = None
    if cols:
        col_names = [c for c in (re.sub(r"[^0-9A-Za-z_]", "", x) for x in cols.split(",")) if c]
        if not col_names:
            return error(code=400, message="列过滤非法：请传逗号分隔的列名")
    sel = ",".join(f"`{c}`" for c in col_names) if col_names else "*"

    target = _MAX_ROWS if limit == 0 else limit
    rows: List[dict] = []
    off = 0
    try:
        while len(rows) < target:
            take = min(_PAGE, target - len(rows))
            sql = f"SELECT {sel} FROM `{table}`{where} LIMIT {take} OFFSET {off}"
            chunk = await query_business(sql, limit=take)
            rows.extend(chunk)
            if len(chunk) < take:
                break
            off += take
    except Exception as e:
        return error(code=500, message=f"查询失败：{e}")

    return success(data={
        **_lookup_payload(name, mod, landing, is_source),
        "flts": flt,
        "columns": col_names,
        "returned": len(rows),
        "rows": rows,
    })


# --------------------------------------------------------------------
# 全表盘点：项目内所有提到的表名清单（静态聚合 + 应用库数据元素绑定）
# --------------------------------------------------------------------

@router.get("/tables")
async def list_all_tables():
    """聚合项目内所有提到的表名（去重、按 base 归一并平铺，不分类）。

    来源：
      1. table_map.json 的 source_tables / landing_tables（22 个模块）
      2. business_tables.json 的 table_name（业务库表清单底稿）
      3. t_data_element.source_table（已创建的数据元素绑定的表）
      4. APP_TABLES 应用 schema 月报存储表（db/init.sql）
    """
    biz_idx = _biz_index()
    merged: dict = {}

    def ensure(base: str, original: str):
        item = merged.setdefault(base, {
            "base": base,
            "originals": [],
            "is_source": False,
            "is_landing": False,
            "is_app": base in APP_TABLES,
            "modules": [],
            "landing_tables": [],
            "resolved_table": "",
            "biz": biz_idx.get(base),
        })
        if original not in item["originals"]:
            item["originals"].append(original)
        return item

    for mod in _load_map()["modules"]:
        mname = mod["name"]
        for s in mod.get("source_tables", []):
            it = ensure(_base_name(s), s)
            it["is_source"] = True
            if mname not in it["modules"]:
                it["modules"].append(mname)
        landing = mod.get("landing_tables") or []
        for t in landing:
            it = ensure(_base_name(t), t)
            it["is_landing"] = True
            if mname not in it["modules"]:
                it["modules"].append(mname)
            if landing:
                it["landing_tables"] = landing
                it["resolved_table"] = landing[0]

    # business_tables.json 底稿：可能带 schema 前缀/大写，统一 base 归一
    for b in _load_biz_tables():
        t = str(b.get("table_name", "")).strip()
        if not t:
            continue
        ensure(_base_name(t), t)

    # 数据元素绑定的表（应用 schema）
    try:
        rows = await query_app_schema(
            "SELECT DISTINCT source_table FROM t_data_element WHERE source_table IS NOT NULL AND source_table <> ''"
        )
        for r in rows:
            t = str(r.get("source_table", "")).strip()
            if not t:
                continue
            ensure(_base_name(t), t)
    except Exception:
        # 应用 schema 不可达时清单仍可用（少一个来源）
        pass

    # 应用 schema 月报存储表（db/init.sql 建表，存在应用 UUID schema 而非业务库）
    for t in APP_TABLES:
        ensure(t, t)

    tables = sorted(merged.values(), key=lambda x: x["base"])
    return success(data={
        "total": len(tables),
        "source_count": sum(1 for t in tables if t["is_source"]),
        "landing_count": sum(1 for t in tables if t["is_landing"]),
        "app_count": sum(1 for t in tables if t["is_app"]),
        "tables": tables,
    })


# --------------------------------------------------------------------
# 单表体检：存在性 / 中文备注 / 估算行数 / 列数 / 前 N 行样例 / 归属核对
# --------------------------------------------------------------------

async def _table_meta(base: str, is_app: bool = False) -> dict | None:
    """查表元数据：存在性 / 表注释 / 估算行数 / 列数。

    业务库表 → netcare schema（只读业务库）；应用表（月报存储）→ 应用 UUID schema（SQLite 应用库）。
    """
    schema = settings.APP_SCHEMA if is_app else "netcare"
    query = query_app_schema if is_app else query_business
    q = base.replace("'", "''")
    if is_app:
        sql = (
            f"SELECT name AS TABLE_NAME, '' AS TABLE_COMMENT, (SELECT count(*) FROM `{q}`) AS TABLE_ROWS "
            f"FROM sqlite_master WHERE type='table' AND LOWER(name)='{q.lower()}'"
        )
    else:
        sql = (
            "SELECT TABLE_NAME, TABLE_COMMENT, TABLE_ROWS FROM information_schema.TABLES "
            f"WHERE LOWER(TABLE_SCHEMA)='{schema.lower()}' AND LOWER(TABLE_NAME)='{q.lower()}'"
        )
    try:
        rows = await query(sql)
    except Exception:
        return None
    if not rows:
        return None
    r = rows[0]
    col_count = None
    if not is_app:
        col_sql = (
            "SELECT COUNT(*) AS C FROM information_schema.COLUMNS "
            f"WHERE LOWER(TABLE_SCHEMA)='{schema.lower()}' AND LOWER(TABLE_NAME)='{q.lower()}'"
        )
        try:
            cr = await query(col_sql)
            if cr and cr[0].get("C") is not None:
                col_count = int(cr[0]["C"])
        except Exception:
            pass
    else:
        try:
            s_rows = await query(f"SELECT * FROM `{q}` LIMIT 1")
            if s_rows:
                col_count = len(s_rows[0].keys())
        except Exception:
            pass
    est = r.get("TABLE_ROWS")
    return {
        "exists": True,
        "table_comment": r.get("TABLE_COMMENT", "") or "",
        "estimated_rows": int(est) if est is not None else None,
        "estimated": True,
        "column_count": col_count,
    }


@router.get("/inspect")
async def inspect_table(
    name: str = Query(..., description="任意表名（源表/落地表/business_tables/数据元素绑定表）"),
    rows: int = Query(20, ge=1, le=200, description="返回前 N 行样例数据"),
):
    """单表体检：核对其归属 / 中文备注 / 行数 / 字段数 / 数据样例，供全表盘点使用。"""
    base = _base_name(name)
    mod, landing, is_source = _resolve(name)
    biz_idx = _biz_index()

    result: dict = {
        "name": name,
        "base": base,
        "is_app": base in APP_TABLES,
        "module": mod["name"] if mod else "",
        "remark": mod.get("remark", "") if mod else "",
        "is_source": bool(is_source),
        "is_landing": bool(mod and not is_source),
        "source_tables": mod["source_tables"] if mod else [],
        "landing_tables": mod["landing_tables"] if mod else [],
        "resolved_table": landing or "",
        "biz": biz_idx.get(base),
    }

    # 数据元素绑定
    try:
        erows = await query_app_schema(
            "SELECT id, element_key, name, data_kind FROM t_data_element "
            "WHERE LOWER(source_table)='" + base.replace("'", "''") + "'"
        )
        result["elements"] = erows
    except Exception:
        result["elements"] = []

    # 元数据 + 样例（应用表查应用 UUID schema，其余查业务库 netcare）
    query = query_app_schema if result["is_app"] else query_business
    meta = await _table_meta(base, result["is_app"])
    result["meta"] = meta

    if meta:
        try:
            sample = await query(
                f"SELECT * FROM `{base}` LIMIT {int(rows)}", limit=int(rows)
            )
        except Exception as e:
            sample = None
            result["note"] = f"数据结构存在但读取数据失败：{e}"
        if sample is not None:
            result["sample"] = {
                "columns": list(sample[0].keys()) if sample else [],
                "rows": sample,
                "returned": len(sample),
            }
        # 与模块落地表一致性检查
        if mod and not is_source and landing and base != _base_name(landing):
            result["match_check"] = (
                f"⚠️ 输入表 [{name}] 是模块[{mod['name']}]的落地表之一，"
                f"但模块第一张落地表为 [{landing}]，直查默认会查第一张。"
            )
    else:
        if mod and is_source:
            result["note"] = (
                f"源表 [{name}] 位于上游库（不在业务库 netcare 中），无法直接查询；"
                f"建议经业务库落地表 [{landing or '无'}] 查询。"
            )
        else:
            if result["is_app"]:
                result["note"] = f"应用 schema（{settings.APP_SCHEMA}）中未找到表 [{base}]（可能 init.sql 未执行）。"
            else:
                result["note"] = f"业务库 netcare 中未找到表 [{base}]（可能未落表、可能仅存在于上游库或命名不一致）。"

    return success(data=result)
