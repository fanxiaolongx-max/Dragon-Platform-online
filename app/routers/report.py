# -*- coding: utf-8 -*-
"""报告管理路由 — 异步版本"""
from typing import List
from fastapi import APIRouter
from app.schemas import (
    ReportTemplateCreate, ReportTemplateOut, ReportTemplateUpdate,
    BlockIn, BlockOut, ReportConfigIn, ReportConfigOut
)
from app.services.report_service import ReportService
from app.core.response import success

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("")
async def list_reports():
    """获取报告列表"""
    service = ReportService()
    reports = await service.list()
    return success(data=[ReportTemplateOut.model_validate(r).model_dump() for r in reports])


@router.post("")
async def create_report(data: ReportTemplateCreate):
    """创建报告"""
    service = ReportService()
    report = await service.create(data.model_dump())
    return success(data=ReportTemplateOut.model_validate(report).model_dump())


@router.get("/{report_id}")
async def get_report(report_id: int):
    """获取报告详情"""
    service = ReportService()
    detail = await service.get_detail(report_id)
    if not detail:
        return success(data=None)
    return success(data=detail)


@router.put("/{report_id}")
async def update_report(report_id: int, data: ReportTemplateUpdate):
    """更新报告"""
    service = ReportService()
    report = await service.update(report_id, data.model_dump(exclude_unset=True))
    if not report:
        return success(data=None)
    return success(data=ReportTemplateOut.model_validate(report).model_dump())


@router.delete("/{report_id}")
async def delete_report(report_id: int):
    """删除报告"""
    service = ReportService()
    deleted = await service.delete(report_id)
    return success(data={"deleted": deleted})


@router.post("/{report_id}/blocks")
async def save_blocks(report_id: int, blocks: List[BlockIn]):
    """保存报告区块（整体替换）"""
    service = ReportService()
    blocks_data = [b.model_dump() for b in blocks]
    saved_blocks = await service.save_blocks(report_id, blocks_data)
    return success(data=[BlockOut.model_validate(b).model_dump() for b in saved_blocks])


@router.put("/{report_id}/configs")
async def save_config(report_id: int, data: ReportConfigIn):
    """保存报告配置"""
    service = ReportService()
    config = await service.save_config(
        report_id=report_id,
        block_id=data.block_id,
        section=data.section,
        config_data=data.config_text
    )
    return success(data=ReportConfigOut.model_validate(config).model_dump())


@router.post("/{report_id}/render")
async def render_report(report_id: int):
    """渲染报告（用于预览和生成）"""
    service = ReportService()
    rendered = await service.render(report_id)
    return success(data=rendered)
