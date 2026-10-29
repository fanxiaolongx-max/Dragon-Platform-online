# -*- coding: utf-8 -*-
"""数据来源 DAO — 基于基座 REST API"""
from typing import List, Optional
from app.db import query_app_schema, execute_app_schema
from app.utils.sql_helper import format_sql_value


class DataSourceDao:
    """数据来源 DAO"""

    @staticmethod
    async def get(source_id: int) -> Optional[dict]:
        """获取单个数据来源"""
        rows = await query_app_schema(
            f"SELECT * FROM t_data_source WHERE id = {source_id} LIMIT 1"
        )
        return rows[0] if rows else None

    @staticmethod
    async def list_all() -> List[dict]:
        """获取所有数据来源"""
        rows = await query_app_schema(
            "SELECT * FROM t_data_source ORDER BY created_at DESC"
        )
        return rows

    @staticmethod
    async def create(data: dict) -> dict:
        """创建数据来源"""
        columns = ", ".join(data.keys())
        values = ", ".join([format_sql_value(v) for v in data.values()])
        sql = f"INSERT INTO t_data_source ({columns}) VALUES ({values})"
        affected = await execute_app_schema(sql)
        if not affected:
            return {}
        # 反查刚插入的记录：source_key 为 UNIQUE，按业务键精确定位，避免全表最大 id 误取并发记录
        source_key = data.get("source_key")
        rows = await query_app_schema(
            f"SELECT * FROM t_data_source WHERE source_key = {format_sql_value(source_key)} LIMIT 1"
        )
        return rows[0] if rows else {}

    @staticmethod
    async def update(source_id: int, data: dict) -> Optional[dict]:
        """更新数据来源"""
        set_clause = ", ".join([
            f"{k} = {format_sql_value(v)}"
            for k, v in data.items()
        ])
        sql = f"UPDATE t_data_source SET {set_clause} WHERE id = {source_id}"
        await execute_app_schema(sql)
        return await DataSourceDao.get(source_id)

    @staticmethod
    async def delete(source_id: int):
        """删除数据来源"""
        await execute_app_schema(f"DELETE FROM t_data_source WHERE id = {source_id}")
