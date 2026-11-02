# -*- coding: utf-8 -*-
"""交互日志与业务表清单路由：日志查询 / 前端上报、表失败标记、业务表清单刷新"""
from typing import Any, Dict

from fastapi import APIRouter, Query, Request

from app.core.response import success
from app.services import ops_service

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/logs")
async def list_logs(
    limit: int = Query(200, ge=1, le=1000, description="最近多少条"),
    days: float = Query(0, ge=0, le=ops_service.RETAIN_DAYS, description="最近多少天，0 = 不限（日志保留 30 天）"),
    kind: str = Query("", description="db / adc / tables / api / ui，空 = 全部"),
    status: str = Query("", description="ok / error，空 = 全部"),
    q: str = Query("", description="关键字（表名、SQL、提问内容、请求编号等）"),
):
    """开发者页与 AI 月报的外部交互日志（基座 API 请求、ADC 对话、业务表清单刷新），新的在前"""
    return success(data=await ops_service.list_logs(limit, days, kind, status, q))


@router.post("/logs")
async def report_logs(payload: Dict[str, Any], request: Request):
    """浏览器上报 ADC 内嵌对话等前端交互"""
    page = ops_service.page_of(request.headers.get("referer", ""), str(payload.get("page") or ""))
    return success(data={"accepted": ops_service.record_client(payload.get("entries"), page)})


@router.get("/tables")
async def table_status():
    """最近一次业务表清单快照与查询失败的表（失败次数、最近错误）"""
    return success(data=await ops_service.snapshot())


@router.post("/tables/refresh")
async def refresh_tables(request: Request, payload: Dict[str, Any] | None = None):
    """重新查询业务库最新表名，对比上次的新增 / 减少并写入日志（60 秒内重复调用直接返回上次结果）"""
    payload = payload or {}
    page = ops_service.page_of(request.headers.get("referer", ""), str(payload.get("page") or ""))
    return success(data=await ops_service.refresh_tables(page, bool(payload.get("force"))))
