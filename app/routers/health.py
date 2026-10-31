# -*- coding: utf-8 -*-
"""健康检查路由"""
import os
from fastapi import APIRouter
from app.db import check_base_api
from app.core.response import success

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def health_check():
    """健康检查接口 - 检查基座 API 连接状态"""
    status = await check_base_api()
    return success(data={"base_api": "ok" if status else "failed"})


@router.get("/dev-workspace", include_in_schema=False)
async def get_dev_workspace():
    """返回开发者工作台 HTML（避免内网基座网关将 .html 静态路径重写回主页）"""
    dev_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "dev.html")
    if os.path.isfile(dev_file):
        with open(dev_file, "r", encoding="utf-8") as f:
            return success(data={"html": f.read()})
    return success(data={"html": ""})
