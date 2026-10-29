# -*- coding: utf-8 -*-
"""数据查询路由 — 异步版本"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Query
from app.services.data_service import DataService
from app.core.response import success, error
from app.db import query_app_schema

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/tables")
async def list_tables(source_db: str = Query("netcare", description="数据库名称")):
    """获取指定数据库的表列表"""
    service = DataService()
    tables = await service.list_tables(source_db)
    return success(data=tables)


@router.get("/columns/{table_name}")
async def get_table_columns(
    table_name: str,
    source_db: str = Query("netcare", description="数据库名称")
):
    """获取指定表的列信息"""
    service = DataService()
    columns = await service.list_columns(table_name, source_db)
    return success(data=columns)


@router.get("/indicators/default")
async def list_default_indicators():
    """获取默认指标集列表"""
    service = DataService()
    indicators = service.list_default_indicators()
    return success(data=indicators)


@router.post("/fetch")
async def fetch_data(payload: Dict[str, Any]):
    """根据数据元素配置获取数据"""
    element_id = payload.get("element_id")
    if not element_id:
        return error(code=400, message="缺少 element_id")

    # 从数据库获取数据元素
    rows = await query_app_schema(f"SELECT * FROM t_data_element WHERE id = {element_id} LIMIT 1")
    if not rows:
        return error(code=404, message="数据元素不存在")

    element = rows[0]
    start = payload.get("start", "")
    end = payload.get("end", "")
    region_code = payload.get("region_code", "")
    repoffice_code = payload.get("repoffice_code", "")

    service = DataService()
    result = await service.fetch_element_data(element, start, end, region_code, repoffice_code)
    return success(data=result)


@router.post("/pivot")
async def pivot_data(payload: Dict[str, Any]):
    """数据透视聚合"""
    element_id = payload.get("element_id")
    if not element_id:
        return error(code=400, message="缺少 element_id")

    # 从数据库获取数据元素
    rows = await query_app_schema(f"SELECT * FROM t_data_element WHERE id = {element_id} LIMIT 1")
    if not rows:
        return error(code=404, message="数据元素不存在")

    element = rows[0]
    dim_field = payload.get("dim_field", "")
    # 多维度分组：dim_fields 优先（支持多选），为空时回退到 dim_field（单选兼容）
    dim_fields = payload.get("dim_fields")
    if not dim_fields or not isinstance(dim_fields, list) or len(dim_fields) == 0:
        dim_fields = [dim_field] if dim_field else []
    metric_field = payload.get("metric_field", "")
    agg = payload.get("agg", "count")
    metrics = payload.get("metrics")
    start = payload.get("start", "")
    end = payload.get("end", "")
    region_code = payload.get("region_code", "")
    repoffice_code = payload.get("repoffice_code", "")
    limit = payload.get("limit", 20)

    service = DataService()
    result = await service.fetch_pivot_data(
        element, dim_field, metric_field, agg, start, end, region_code, repoffice_code, limit,
        dim_fields=dim_fields,
        metrics=metrics,
    )
    return success(data=result)
