# -*- coding: utf-8 -*-
"""数据元素管理路由 — 异步版本"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Query
from app.schemas import DataElementCreate, DataElementOut, DataElementUpdate
from app.services.data_element_service import DataElementService
from app.core.response import success
from app.db import query_app_schema

router = APIRouter(prefix="/data-elements", tags=["data-elements"])


@router.get("")
async def list_data_elements():
    """获取所有数据元素列表"""
    service = DataElementService()
    elements = await service.list_all()
    return success(data=[DataElementOut.model_validate(e).model_dump() for e in elements])


@router.get("/grouped")
async def get_grouped_data_elements():
    """获取分组后的数据元素（按 category 分组）"""
    service = DataElementService()
    elements = await service.list_all()

    # 按 category 分组
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for elem in elements:
        category = elem.get("category", "默认")
        if category not in grouped:
            grouped[category] = []
        grouped[category].append(DataElementOut.model_validate(elem).model_dump())

    return success(data=grouped)


@router.post("")
async def create_data_element(data: DataElementCreate):
    """创建数据元素"""
    service = DataElementService()
    element = await service.create(data.model_dump())
    return success(data=DataElementOut.model_validate(element).model_dump())


@router.get("/{element_id}")
async def get_data_element(element_id: int):
    """根据 ID 获取数据元素详情"""
    service = DataElementService()
    element = await service.get_by_id(element_id)
    if not element:
        return success(data=None)
    return success(data=DataElementOut.model_validate(element).model_dump())


@router.put("/{element_id}")
async def update_data_element(element_id: int, data: DataElementUpdate):
    """更新数据元素"""
    service = DataElementService()
    element = await service.update(element_id, data.model_dump(exclude_unset=True))
    if not element:
        return success(data=None)
    return success(data=DataElementOut.model_validate(element).model_dump())


@router.delete("/{element_id}")
async def delete_data_element(element_id: int):
    """删除数据元素"""
    service = DataElementService()
    deleted = await service.delete(element_id)
    return success(data={"deleted": deleted})
