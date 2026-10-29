# -*- coding: utf-8 -*-
"""数据元素 DAO — 基于基座 REST API"""
from typing import List, Optional
from app.db import query_app_schema, execute_app_schema
from app.utils.sql_helper import format_sql_value


class DataElementDao:
    """数据元素 DAO"""

    @staticmethod
    async def get(element_id: int) -> Optional[dict]:
        """获取单个数据元素"""
        rows = await query_app_schema(
            f"SELECT * FROM t_data_element WHERE id = {element_id} LIMIT 1"
        )
        return rows[0] if rows else None

    @staticmethod
    async def list_all() -> List[dict]:
        """获取所有数据元素"""
        rows = await query_app_schema(
            "SELECT * FROM t_data_element ORDER BY created_at DESC"
        )
        return rows

    @staticmethod
    async def create(data: dict) -> dict:
        """创建数据元素"""
        columns = ", ".join(data.keys())
        values = ", ".join([format_sql_value(v) for v in data.values()])
        sql = f"INSERT INTO t_data_element ({columns}) VALUES ({values})"
        affected = await execute_app_schema(sql)
        if not affected:
            return {}
        # 反查刚插入的记录：element_key 为 UNIQUE，按业务键精确定位，避免全表最大 id 误取并发记录
        element_key = data.get("element_key")
        rows = await query_app_schema(
            f"SELECT * FROM t_data_element WHERE element_key = {format_sql_value(element_key)} LIMIT 1"
        )
        return rows[0] if rows else {}

    @staticmethod
    async def update(element_id: int, data: dict) -> Optional[dict]:
        """更新数据元素"""
        set_clause = ", ".join([
            f"{k} = {format_sql_value(v)}"
            for k, v in data.items()
        ])
        sql = f"UPDATE t_data_element SET {set_clause} WHERE id = {element_id}"
        await execute_app_schema(sql)
        return await DataElementDao.get(element_id)

    @staticmethod
    async def delete(element_id: int):
        """删除数据元素"""
        await execute_app_schema(f"DELETE FROM t_data_element WHERE id = {element_id}")
