# -*- coding: utf-8 -*-
"""报告相关 DAO — 基于基座 REST API"""
from typing import List, Optional
from app.db import query_app_schema, execute_app_schema
from app.utils.sql_helper import format_sql_value


class ReportDao:
    """报告模板 DAO"""

    @staticmethod
    async def get(report_id: int) -> Optional[dict]:
        """获取单个报告"""
        rows = await query_app_schema(
            f"SELECT * FROM t_report_template WHERE id = {report_id} LIMIT 1"
        )
        return rows[0] if rows else None

    @staticmethod
    async def list_all(skip: int = 0, limit: int = 100) -> List[dict]:
        """获取报告列表"""
        rows = await query_app_schema(
            f"SELECT * FROM t_report_template ORDER BY created_at DESC LIMIT {limit} OFFSET {skip}"
        )
        return rows

    @staticmethod
    async def create(data: dict) -> dict:
        """创建报告"""
        columns = ", ".join(data.keys())
        values = ", ".join([format_sql_value(v) for v in data.values()])
        sql = f"INSERT INTO t_report_template ({columns}) VALUES ({values})"
        affected = await execute_app_schema(sql)
        if not affected:
            return {}
        # 反查刚插入的记录：按 name 精确定位（同批新建 name 唯一，避免全表最大 id 误取并发记录）
        name = data.get("name")
        rows = await query_app_schema(
            f"SELECT * FROM t_report_template WHERE name = {format_sql_value(name)} ORDER BY id DESC LIMIT 1"
        )
        return rows[0] if rows else {}

    @staticmethod
    async def update(report_id: int, data: dict) -> Optional[dict]:
        """更新报告"""
        set_clause = ", ".join([
            f"{k} = {format_sql_value(v)}"
            for k, v in data.items()
        ])
        sql = f"UPDATE t_report_template SET {set_clause} WHERE id = {report_id}"
        await execute_app_schema(sql)
        return await ReportDao.get(report_id)

    @staticmethod
    async def delete(report_id: int):
        """删除报告"""
        await execute_app_schema(f"DELETE FROM t_report_template WHERE id = {report_id}")


class BlockDao:
    """报告区块 DAO"""

    @staticmethod
    async def get(block_id: int) -> Optional[dict]:
        """获取单个区块"""
        rows = await query_app_schema(
            f"SELECT * FROM t_report_block WHERE id = {block_id} LIMIT 1"
        )
        return rows[0] if rows else None

    @staticmethod
    async def list_by_report(report_id: int) -> List[dict]:
        """按报告 ID 获取区块列表"""
        rows = await query_app_schema(
            f"SELECT * FROM t_report_block WHERE report_id = {report_id} ORDER BY order_no"
        )
        return rows

    @staticmethod
    async def create(data: dict) -> dict:
        """创建区块"""
        columns = ", ".join(data.keys())
        values = ", ".join([format_sql_value(v) for v in data.values()])
        sql = f"INSERT INTO t_report_block ({columns}) VALUES ({values})"
        affected = await execute_app_schema(sql)
        if not affected:
            return {}
        # 反查刚插入的记录：按 report_id + order_no 精确定位（insert 后同批内唯一）
        report_id = data.get("report_id")
        order_no = data.get("order_no", 0)
        rows = await query_app_schema(
            f"SELECT * FROM t_report_block WHERE report_id = {report_id} AND order_no = {order_no} LIMIT 1"
        )
        return rows[0] if rows else {}

    @staticmethod
    async def update(block_id: int, data: dict) -> Optional[dict]:
        """更新区块"""
        set_clause = ", ".join([
            f"{k} = {format_sql_value(v)}"
            for k, v in data.items()
        ])
        sql = f"UPDATE t_report_block SET {set_clause} WHERE id = {block_id}"
        await execute_app_schema(sql)
        return await BlockDao.get(block_id)

    @staticmethod
    async def delete(block_id: int):
        """删除区块"""
        await execute_app_schema(f"DELETE FROM t_report_block WHERE id = {block_id}")

    @staticmethod
    async def delete_by_report(report_id: int):
        """删除报告的所有区块"""
        await execute_app_schema(f"DELETE FROM t_report_block WHERE report_id = {report_id}")


class ConfigDao:
    """报告配置 DAO"""

    @staticmethod
    async def list_by_report(report_id: int) -> List[dict]:
        """按报告 ID 获取配置列表"""
        rows = await query_app_schema(
            f"SELECT * FROM t_report_config WHERE report_id = {report_id}"
        )
        return rows

    @staticmethod
    async def list_by_block(report_id: int, block_id: int) -> List[dict]:
        """按报告和区块 ID 获取配置列表"""
        rows = await query_app_schema(
            f"SELECT * FROM t_report_config WHERE report_id = {report_id} AND block_id = {block_id}"
        )
        return rows

    @staticmethod
    async def create(data: dict) -> dict:
        """创建配置"""
        columns = ", ".join(data.keys())
        values = ", ".join([format_sql_value(v) for v in data.values()])
        sql = f"INSERT INTO t_report_config ({columns}) VALUES ({values})"
        affected = await execute_app_schema(sql)
        if not affected:
            return {}
        # 反查刚插入的记录：按 report_id + block_id + section 精确定位
        report_id = data.get("report_id")
        block_id = data.get("block_id")
        section = data.get("section", "style")
        block_cond = f"block_id = {format_sql_value(block_id)}" if block_id is not None else "block_id IS NULL"
        rows = await query_app_schema(
            f"SELECT * FROM t_report_config WHERE report_id = {report_id} "
            f"AND {block_cond} AND section = {format_sql_value(section)} LIMIT 1"
        )
        return rows[0] if rows else {}

    @staticmethod
    async def update(config_id: int, data: dict) -> Optional[dict]:
        """更新配置"""
        set_clause = ", ".join([
            f"{k} = {format_sql_value(v)}"
            for k, v in data.items()
        ])
        sql = f"UPDATE t_report_config SET {set_clause} WHERE id = {config_id}"
        await execute_app_schema(sql)
        rows = await query_app_schema(
            f"SELECT * FROM t_report_config WHERE id = {config_id} LIMIT 1"
        )
        return rows[0] if rows else None
