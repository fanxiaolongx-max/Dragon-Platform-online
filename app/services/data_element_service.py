# -*- coding: utf-8 -*-
"""数据元素服务"""
from typing import List, Optional, Dict, Any
from app.dao.data_element_dao import DataElementDao


class DataElementService:
    """数据元素业务服务"""

    def __init__(self):
        self.dao = DataElementDao()

    async def list_all(self) -> List[dict]:
        """获取数据元素列表"""
        return await self.dao.list_all()

    async def get_by_id(self, element_id: int) -> Optional[dict]:
        """根据 ID 获取数据元素"""
        return await self.dao.get(element_id)

    async def create(self, data: Dict[str, Any]) -> dict:
        """创建数据元素"""
        return await self.dao.create(data)

    async def update(self, element_id: int, data: Dict[str, Any]) -> Optional[dict]:
        """更新数据元素"""
        element = await self.dao.get(element_id)
        if not element:
            return None

        return await self.dao.update(element_id, data)

    async def delete(self, element_id: int) -> bool:
        """删除数据元素"""
        element = await self.dao.get(element_id)
        if not element:
            return False

        await self.dao.delete(element_id)
        return True
