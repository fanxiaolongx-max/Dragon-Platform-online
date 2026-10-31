# -*- coding: utf-8 -*-
"""AI 月报路由：月报文档读写、格子 / 提示词增删改、配方按月取数"""
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.response import success
from app.services import air_service

router = APIRouter(prefix="/air", tags=["ai-report"])


class CellIn(BaseModel):
    chapter_id: Optional[str] = None
    prompt: Optional[str] = None
    span: Optional[int] = None
    height: Optional[int] = None


class StyleIn(BaseModel):
    prompt: str = ""


@router.get("/documents")
async def list_documents():
    """全部 AI 月报（id、名称、报告月份、更新时间）"""
    return success(data=await air_service.list_documents())


@router.get("/documents/{report_id}")
async def read_document(report_id: str):
    """完整月报文档（章节、格子、提示词、配方、本月结果）"""
    return success(data=await air_service.read_document(report_id))


@router.get("/documents/{report_id}/outline")
async def read_outline(report_id: str):
    """精简大纲：章节、格子 id、格子名、提示词"""
    return success(data=air_service.outline(await air_service.read_document(report_id)))


@router.post("/documents")
async def save_document(payload: Dict[str, Any]):
    """保存整份月报（无 id 或 id 不存在时新建）"""
    return success(data=await air_service.save_document(payload))


@router.delete("/documents/{report_id}")
async def delete_document(report_id: str):
    return success(data=await air_service.delete_document(report_id))


@router.post("/documents/{report_id}/cells")
async def add_cell(report_id: str, payload: CellIn):
    """新增格子（默认加到最后一个章节）"""
    return success(data=await air_service.upsert_cell(report_id, None, payload.chapter_id, payload.prompt, payload.span, payload.height))


@router.put("/documents/{report_id}/cells/{cell_id}")
async def update_cell(report_id: str, cell_id: str, payload: CellIn):
    """修改格子提示词 / 宽度（1-12 栏）/ 高度"""
    return success(data=await air_service.upsert_cell(report_id, cell_id, None, payload.prompt, payload.span, payload.height))


@router.delete("/documents/{report_id}/cells/{cell_id}")
async def delete_cell(report_id: str, cell_id: str):
    return success(data=await air_service.delete_cell(report_id, cell_id))


@router.put("/documents/{report_id}/style")
async def set_style(report_id: str, payload: StyleIn):
    """修改月报整体风格提示词"""
    return success(data=await air_service.set_style_prompt(report_id, payload.prompt))


@router.post("/run-data")
async def run_data(payload: Dict[str, Any]):
    """按报告月份执行配方里的 SQL 来源，返回 compute 的输入"""
    return success(data=await air_service.run_data(str(payload.get("month") or ""), payload.get("recipe") or {}))


@router.get("/month-values")
async def month_values(month: str, offset: int = 0):
    """SQL 占位符在某个报告月份的取值（{{month}}、{{month_start}} 等）"""
    return success(data=air_service.month_values(month, offset))
