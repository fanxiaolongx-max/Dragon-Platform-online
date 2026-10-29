# -*- coding: utf-8 -*-
"""健康检查路由"""
from fastapi import APIRouter
from app.db import check_base_api
from app.core.response import success

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def health_check():
    """健康检查接口 - 检查基座 API 连接状态"""
    status = await check_base_api()
    return success(data={"base_api": "ok" if status else "failed"})
