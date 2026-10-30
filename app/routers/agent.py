# -*- coding: utf-8 -*-
"""Dragon Claw 能力路由：能力清单 + 受控执行器（前端在 AI 提出 dragon-action 后调用）"""
from typing import Any, Dict

from fastapi import APIRouter, Request

from app.core.response import success
from app.services import agent_service

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/capabilities")
async def get_capabilities():
    """AI 可调用的工具清单、数据源与协议提示词"""
    return success(data=agent_service.capabilities())


@router.post("/execute")
async def execute_tool(payload: Dict[str, Any], request: Request):
    """执行一个工具。写操作首次调用只返回预览与确认令牌，带 confirm_token 再次调用才真正写入。"""
    client = request.client.host if request.client else ""
    result = await agent_service.execute(
        payload.get("tool"), payload.get("args") or {}, payload.get("confirm_token"), client=client
    )
    return success(data=result)
