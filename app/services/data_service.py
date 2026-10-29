# -*- coding: utf-8 -*-
"""报告库数据取数服务（阶段3）— 异步版本，基于基座 REST API"""
import json
import os
from datetime import datetime, timedelta
from typing import Optional

from app.core.exceptions import BusinessError, DataSourceError
from app.db import query_business, query_app_schema

# 内置默认指标集
DEFAULT_INDICATORS = [
    {
        "ref": "risk_completion_rate",
        "name": "中高风险处置完成率",
        "unit": "%",
        "desc": "中高风险任务的处置完成率（Closed 数 / 总数）",
    },
]

# 字段 SQL 标识符清洗
_HAZARD_CHARS = set("`'\";(){}[]\\ \t\r\n=*%&|<>")


def _sanitize_ident(value, label="标识符"):
    """清洗 SQL 标识符（表名/字段名/别名），拒绝危险字符与空白，支持中文。"""
    if not value:
        raise BusinessError(message=f"{label}不能为空")
    if any(ch in _HAZARD_CHARS for ch in value):
        raise BusinessError(message=f"{label}含非法字符: {value}")
    if value[0].isdigit():
        raise BusinessError(message=f"{label}不能以数字开头: {value}")
    return value


class DataService:
    """报告库取数服务（异步版本）"""

    def __init__(self):
        pass

    # ---------- 元数据：表 / 字段 ----------
    async def list_tables(self, source_db: str = "netcare") -> list:
        """列出指定库下的数据表（真实表名，不含视图），包含表注释。"""
        dbname = _sanitize_ident(source_db or "netcare", "库名")
        sql = (
            "SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES "
            f"WHERE LOWER(TABLE_SCHEMA) = '{dbname.lower()}' AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME"
        )
        try:
            # limit=1000 为基座单页上限；netcare 库实际约 441 张表，默认 100 会截断
            rows = await query_business(sql, limit=1000)

            # 组装返回结果
            result = []
            for r in rows:
                table_name = r["TABLE_NAME"]
                table_comment = r.get("TABLE_COMMENT", "") or ""

                # 显示名称：如果有注释就显示 "表名 (注释)"，否则只显示表名
                display_name = f"{table_name} ({table_comment})" if table_comment else table_name

                result.append({
                    "table_name": table_name,
                    "table_comment": table_comment,
                    "display_name": display_name
                })
            return result
        except Exception as e:
            raise DataSourceError(message=f"获取数据表失败: {e}") from e

    async def list_columns(self, table: str, source_db: str = "netcare") -> list:
        """列出指定表的字段及类型/注释。"""
        tbl = _sanitize_ident(table, "表名")
        dbname = _sanitize_ident(source_db or "netcare", "库名")
        sql = (
            "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT, ORDINAL_POSITION "
            "FROM information_schema.COLUMNS "
            f"WHERE LOWER(TABLE_SCHEMA)='{dbname.lower()}' AND LOWER(TABLE_NAME)='{tbl.lower()}' "
            "ORDER BY ORDINAL_POSITION"
        )
        try:
            rows = await query_business(sql)
            return [
                {"field": r["COLUMN_NAME"], "type": r["DATA_TYPE"], "comment": r.get("COLUMN_COMMENT", "")}
                for r in rows
            ]
        except Exception as e:
            raise DataSourceError(message=f"获取字段列表失败: {e}") from e

    # ---------- 默认指标集 ----------
    def list_default_indicators(self) -> list:
        return DEFAULT_INDICATORS

    # ---------- 取数 ----------
    async def fetch_element_data(
        self,
        element: dict,
        start: str = "",
        end: str = "",
        region_code: str = "",
        repoffice_code: str = "",
    ) -> dict:
        """按数据元素配置取数（表单表格数据 / 指标单值）。"""
        if element.get("data_kind") == "indicator":
            return await self._fetch_indicator(element, start, end, region_code, repoffice_code)
        return await self._fetch_form(element, start, end, region_code, repoffice_code)

    def _selected_fields(self, element: dict) -> list:
        """解析 field_select JSON，返回 [{field, alias}]；未配置时为空。"""
        field_select = element.get("field_select")
        if not field_select:
            return []
        try:
            arr = json.loads(field_select)
            if not isinstance(arr, list):
                return []
            return [
                {
                    "field": str(x.get("field", "")).strip(),
                    "alias": str(x.get("alias", "")).strip(),
                }
                for x in arr
                if str(x.get("field", "")).strip()
            ]
        except (ValueError, TypeError):
            return []

    async def _fetch_form(self, element: dict, start, end, region_code, repoffice_code) -> dict:
        """表单数据：选字段列出表格行。"""
        table = _sanitize_ident(element.get("source_table"), "数据表")
        dbname = _sanitize_ident(element.get("source_db") or "netcare", "库名")
        fields = self._selected_fields(element)
        if not fields:
            raise BusinessError(message=f"数据元素「{element.get('name')}」未配置展示字段")

        # 构造 SELECT 列（含别名）
        select_parts = []
        headers = []
        for f in fields:
            col = _sanitize_ident(f["field"], "字段")
            alias = _sanitize_ident(f.get("alias") or f["field"], "字段别名")
            select_parts.append(f"`{col}` AS `{alias}`")
            headers.append(alias)

        # WHERE：时间段 + 代表处 + 地区部
        where = []

        # 获取时间字段：优先使用元素配置的，否则尝试常见的时间字段名
        time_field = element.get("time_field")
        if not time_field:
            common_time_fields = ['period_month', 'time_field', 'create_time', 'update_time', 'date']
            columns_info = await self.list_columns(table, dbname)
            column_names = [col['field'].lower() for col in columns_info]
            for common_field in common_time_fields:
                if common_field.lower() in column_names:
                    time_field = common_field
                    break

        tf = _sanitize_ident(time_field, "时间字段") if time_field else ""

        # 智能处理时间范围
        if tf and (start or end):
            sample_sql = f"SELECT `{tf}` FROM `{dbname}`.`{table}` WHERE `{tf}` IS NOT NULL LIMIT 1"
            sample_rows = await query_business(sample_sql)
            sample_result = sample_rows[0][tf] if sample_rows else None

            if sample_result:
                sample_str = str(sample_result)
                if len(sample_str) == 7 and sample_str[4] == '-':
                    # YYYY-MM 格式
                    if start:
                        start_ym = start[:7] if len(start) >= 7 else start
                        where.append(f"`{tf}` >= '{start_ym}'")
                    if end:
                        end_ym = end[:7] if len(end) >= 7 else end
                        where.append(f"`{tf}` <= '{end_ym}'")
                elif len(sample_str) > 10 and ' ' in sample_str:
                    # DATETIME 格式
                    if start:
                        where.append(f"`{tf}` >= '{start}'")
                    if end:
                        try:
                            end_date = datetime.strptime(end[:10], '%Y-%m-%d')
                            next_day = end_date + timedelta(days=1)
                            where.append(f"`{tf}` < '{next_day.strftime('%Y-%m-%d')}'")
                        except:
                            where.append(f"`{tf}` <= '{end}'")
                else:
                    # DATE 格式
                    if start:
                        where.append(f"`{tf}` >= '{start}'")
                    if end:
                        try:
                            end_date = datetime.strptime(end[:10], '%Y-%m-%d')
                            next_day = end_date + timedelta(days=1)
                            where.append(f"`{tf}` < '{next_day.strftime('%Y-%m-%d')}'")
                        except:
                            where.append(f"`{tf}` <= '{end}'")

        if element.get("region_field") and region_code:
            rf = _sanitize_ident(element.get("region_field"), "地区部字段")
            where.append(f"`{rf}` = '{region_code}'")
        if element.get("reoffice_field") and repoffice_code:
            of = _sanitize_ident(element.get("reoffice_field"), "代表处字段")
            where.append(f"`{of}` = '{repoffice_code}'")

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        sql_text = (
            f"SELECT {', '.join(select_parts)} FROM `{dbname}`.`{table}`{where_sql} "
            "LIMIT 200"
        )
        try:
            rows = await query_business(sql_text)

            # 格式化时间字段
            formatted_rows = []
            for row in rows:
                formatted_row = {}
                for key, value in row.items():
                    if isinstance(value, datetime):
                        formatted_row[key] = value.strftime('%Y-%m-%d %H:%M:%S')
                    elif isinstance(value, str) and 'T' in value and len(value) >= 19:
                        try:
                            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
                            formatted_row[key] = dt.strftime('%Y-%m-%d %H:%M:%S')
                        except:
                            formatted_row[key] = value
                    else:
                        formatted_row[key] = value
                formatted_rows.append(formatted_row)

            return {
                "kind": "form",
                "columns": list(rows[0].keys()) if rows else headers,
                "rows": formatted_rows,
                "total": len(formatted_rows),
            }
        except Exception as e:
            raise DataSourceError(message=f"表单数据查询失败: {e}") from e

    async def _fetch_indicator(self, element: dict, start, end, region_code, repoffice_code) -> dict:
        """指标单值：默认指标集 或 选表聚合计算。"""
        if element.get("calc_source") == "default_set":
            return await self._fetch_default_indicator(element, region_code, repoffice_code)
        return await self._fetch_db_calc(element, start, end, region_code, repoffice_code)

    async def _fetch_default_indicator(self, element: dict, region_code, repoffice_code) -> dict:
        """默认指标集"""
        ref = element.get("static_ref") or element.get("element_key")
        if ref == "risk_completion_rate":
            # TODO: 实现风险完成率指标计算（需要查询业务库）
            # 这里暂时返回模拟数据
            return {
                "kind": "indicator",
                "value": 85.5,
                "unit": "%",
                "meta": {"completed": 85, "total": 100},
            }
        raise BusinessError(message=f"未知默认指标: {ref}")

    async def _fetch_db_calc(self, element: dict, start, end, region_code, repoffice_code) -> dict:
        """选表计算单值：对字段做 count/sum/avg/max/min。"""
        table = _sanitize_ident(element.get("source_table"), "数据表")
        dbname = _sanitize_ident(element.get("source_db") or "netcare", "库名")
        ctx = {}
        if element.get("field_select"):
            try:
                parsed = json.loads(element.get("field_select"))
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, dict):
                ctx = parsed
            elif isinstance(parsed, list) and parsed:
                first = parsed[0]
                if isinstance(first, dict):
                    ctx = first
        agg_field = str(ctx.get("agg_field") or ctx.get("field") or "").strip()
        agg_way = str(ctx.get("agg_way") or ctx.get("agg") or "count").lower()
        if agg_way not in ("count", "sum", "avg", "max", "min"):
            agg_way = "count"

        if agg_way == "count":
            agg_expr = "COUNT(*)"
        else:
            if not agg_field:
                raise BusinessError(message="聚合方式非 count，必须配置聚合字段")
            agg_field = _sanitize_ident(agg_field, "聚合字段")
            agg_expr = f"{agg_way.upper()}(`{agg_field}`)"

        where = []
        tf = _sanitize_ident(element.get("time_field"), "时间字段") if element.get("time_field") else ""

        if tf and (start or end):
            sample_sql = f"SELECT `{tf}` FROM `{dbname}`.`{table}` WHERE `{tf}` IS NOT NULL LIMIT 1"
            sample_rows = await query_business(sample_sql)
            sample_result = sample_rows[0][tf] if sample_rows else None

            if sample_result:
                sample_str = str(sample_result)
                if len(sample_str) == 7 and sample_str[4] == '-':
                    if start:
                        start_ym = start[:7] if len(start) >= 7 else start
                        where.append(f"`{tf}` >= '{start_ym}'")
                    if end:
                        end_ym = end[:7] if len(end) >= 7 else end
                        where.append(f"`{tf}` <= '{end_ym}'")
                elif len(sample_str) > 10 and ' ' in sample_str:
                    if start:
                        where.append(f"`{tf}` >= '{start}'")
                    if end:
                        try:
                            end_date = datetime.strptime(end[:10], '%Y-%m-%d')
                            next_day = end_date + timedelta(days=1)
                            where.append(f"`{tf}` < '{next_day.strftime('%Y-%m-%d')}'")
                        except:
                            where.append(f"`{tf}` <= '{end}'")
                else:
                    if start:
                        where.append(f"`{tf}` >= '{start}'")
                    if end:
                        try:
                            end_date = datetime.strptime(end[:10], '%Y-%m-%d')
                            next_day = end_date + timedelta(days=1)
                            where.append(f"`{tf}` < '{next_day.strftime('%Y-%m-%d')}'")
                        except:
                            where.append(f"`{tf}` <= '{end}'")

        if element.get("region_field") and region_code:
            rf = _sanitize_ident(element.get("region_field"), "地区部字段")
            where.append(f"`{rf}` = '{region_code}'")
        if element.get("reoffice_field") and repoffice_code:
            of = _sanitize_ident(element.get("reoffice_field"), "代表处字段")
            where.append(f"`{of}` = '{repoffice_code}'")

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        sql_text = f"SELECT {agg_expr} AS V FROM `{dbname}`.`{table}`{where_sql}"
        try:
            rows = await query_business(sql_text)
            value = rows[0]["V"] if rows else None
            return {"kind": "indicator", "value": value, "unit": "", "meta": None}
        except Exception as e:
            raise DataSourceError(message=f"指标计算查询失败: {e}") from e

    # ---------- 数据透视（阶段4） ----------
    async def fetch_pivot_data(
        self,
        element: dict,
        dim_field: str = "",
        metric_field: str = "",
        agg: str = "count",
        start: str = "",
        end: str = "",
        region_code: str = "",
        repoffice_code: str = "",
        limit: int = 20,
        dim_fields: list = None,
        metrics: list = None,
    ) -> list:
        """对绑定数据元素所在表做数据透视聚合（GROUP BY 维度 + 聚合度量）。

        metrics 为多度量配置，每项形如 {"field": "...", "agg": "sum"}，
        每个度量使用各自聚合方式，生成 VALUE_0/VALUE_1/... 多聚合列。
        未传 metrics 时回退到旧的 metric_field + agg 单度量配置（VALUE 列），保持兼容。
        """
        table = _sanitize_ident(element.get("source_table"), "数据表")
        dbname = _sanitize_ident(element.get("source_db") or "netcare", "库名")

        # 处理维度字段
        if dim_fields and isinstance(dim_fields, list) and len(dim_fields) > 0:
            dims = [_sanitize_ident(f, f"维度字段[{i}]") for i, f in enumerate(dim_fields)]
        elif dim_field:
            dims = [_sanitize_ident(dim_field, "维度字段")]
        else:
            raise BusinessError(message="至少需要一个维度字段")

        # 归一化度量配置：metrics 多度量优先，否则回退 metric_field+agg 单度量
        metric_specs = []
        if metrics and isinstance(metrics, list) and len(metrics) > 0:
            for i, m in enumerate(metrics):
                if not isinstance(m, dict) or not m.get("field"):
                    continue
                f = _sanitize_ident(str(m.get("field")), f"度量字段[{i}]")
                a = (str(m.get("agg")) or "count").lower()
                if a not in ("count", "sum", "avg", "max", "min"):
                    a = "count"
                metric_specs.append({"field": f, "agg": a})
        if not metric_specs:
            a = (agg or "count").lower()
            if a not in ("count", "sum", "avg", "max", "min"):
                a = "count"
            if a == "count":
                metric_specs = [{"field": "", "agg": "count"}]
            else:
                if not metric_field:
                    raise BusinessError(message="聚合方式非 count，必须配置度量字段")
                metric_specs = [{"field": _sanitize_ident(metric_field, "度量字段"), "agg": a}]

        # 生成聚合表达式：多度量时 VALUE_0/VALUE_1/...，单度量时兼容旧 VALUE 列
        multi_metric = len(metric_specs) > 1
        agg_exprs = []
        for i, spec in enumerate(metric_specs):
            if spec["agg"] == "count":
                expr = "COUNT(*)"
            else:
                expr = f"{spec['agg'].upper()}(`{spec['field']}`)"
            agg_exprs.append(f"{expr} AS VALUE_{i}" if multi_metric else f"{expr} AS VALUE")

        where = []
        tf = _sanitize_ident(element.get("time_field"), "时间字段") if element.get("time_field") else ""
        if tf and start:
            where.append(f"`{tf}` >= '{start}'")
        if tf and end:
            where.append(f"`{tf}` <= '{end}'")
        if element.get("region_field") and region_code:
            rf = _sanitize_ident(element.get("region_field"), "地区部字段")
            where.append(f"`{rf}` = '{region_code}'")
        if element.get("reoffice_field") and repoffice_code:
            of = _sanitize_ident(element.get("reoffice_field"), "代表处字段")
            where.append(f"`{of}` = '{repoffice_code}'")

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        try:
            lim = int(limit)
        except (TypeError, ValueError):
            lim = 20
        if lim <= 0:
            lim = 20

        # 构建 SELECT 和 GROUP BY 子句
        select_parts = [f"`{d}` AS DIM_{i}" for i, d in enumerate(dims)]
        select_parts.extend(agg_exprs)
        group_by_clause = ", ".join([f"`{d}`" for d in dims])

        sql_text = (
            f"SELECT {', '.join(select_parts)} "
            f"FROM `{dbname}`.`{table}`{where_sql} "
            f"GROUP BY {group_by_clause} ORDER BY VALUE_0 DESC LIMIT {lim}"
            if multi_metric
            else f"SELECT {', '.join(select_parts)} "
            f"FROM `{dbname}`.`{table}`{where_sql} "
            f"GROUP BY {group_by_clause} ORDER BY VALUE DESC LIMIT {lim}"
        )
        try:
            rows = await query_business(sql_text)
        except Exception as e:
            raise DataSourceError(message=f"数据透视查询失败: {e}") from e

        # 返回结果：根据维度数量返回不同格式
        if len(dims) == 1:
            if multi_metric:
                return [
                    {
                        "name": str(r.get(f"DIM_0")) if r.get(f"DIM_0") is not None else "（空）",
                        "values": [float(r.get(f"VALUE_{i}") or 0) for i in range(len(metric_specs))],
                    }
                    for r in rows
                ]
            return [
                {
                    "name": str(r.get(f"DIM_0")) if r.get(f"DIM_0") is not None else "（空）",
                    "value": float(r.get("VALUE") or 0),
                }
                for r in rows
            ]
        else:
            result = []
            for r in rows:
                item = {"dims": [], "value": float(r.get("VALUE") or 0)}
                if multi_metric:
                    item["values"] = [float(r.get(f"VALUE_{i}") or 0) for i in range(len(metric_specs))]
                for i in range(len(dims)):
                    item["dims"].append(str(r.get(f"DIM_{i}")) if r.get(f"DIM_{i}") is not None else "（空）")
                result.append(item)
            return result
