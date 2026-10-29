# -*- coding: utf-8 -*-
"""数据来源管理路由 — 异步版本"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter
from app.schemas import DataSourceCreate, DataSourceOut, DataSourceUpdate
from app.services.data_source_service import DataSourceService
from app.core.response import success

router = APIRouter(prefix="/data-sources", tags=["data-sources"])


@router.get("")
async def list_data_sources():
    """获取所有数据来源列表"""
    service = DataSourceService()
    sources = await service.list_all()
    return success(data=[DataSourceOut.model_validate(s).model_dump() for s in sources])


@router.post("")
async def create_data_source(data: DataSourceCreate):
    """创建数据来源"""
    service = DataSourceService()
    source = await service.create(data.model_dump())
    return success(data=DataSourceOut.model_validate(source).model_dump())


@router.get("/{source_id}")
async def get_data_source(source_id: int):
    """根据 ID 获取数据来源详情"""
    service = DataSourceService()
    source = await service.get_by_id(source_id)
    if not source:
        return success(data=None)
    return success(data=DataSourceOut.model_validate(source).model_dump())


@router.put("/{source_id}")
async def update_data_source(source_id: int, data: DataSourceUpdate):
    """更新数据来源"""
    service = DataSourceService()
    source = await service.update(source_id, data.model_dump(exclude_unset=True))
    if not source:
        return success(data=None)
    return success(data=DataSourceOut.model_validate(source).model_dump())


@router.delete("/{source_id}")
async def delete_data_source(source_id: int):
    """删除数据来源"""
    service = DataSourceService()
    deleted = await service.delete(source_id)
    return success(data={"deleted": deleted})
