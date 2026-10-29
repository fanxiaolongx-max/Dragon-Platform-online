# -*- coding: utf-8 -*-
"""数据来源服务"""
from typing import List, Optional, Dict, Any
from app.dao.data_source_dao import DataSourceDao


class DataSourceService:
    """数据来源业务服务"""

    def __init__(self):
        self.dao = DataSourceDao()

    async def list_all(self) -> List[dict]:
        """获取数据来源列表"""
        return await self.dao.list_all()

    async def get_by_id(self, source_id: int) -> Optional[dict]:
        """根据 ID 获取单个数据来源"""
        return await self.dao.get(source_id)

    async def create(self, data: Dict[str, Any]) -> dict:
        """创建数据来源"""
        return await self.dao.create(data)

    async def update(self, source_id: int, data: Dict[str, Any]) -> Optional[dict]:
        """更新数据来源"""
        source = await self.dao.get(source_id)
        if not source:
            return None

        return await self.dao.update(source_id, data)

    async def delete(self, source_id: int) -> bool:
        """删除数据来源"""
        source = await self.dao.get(source_id)
        if not source:
            return False

        await self.dao.delete(source_id)
        return True
