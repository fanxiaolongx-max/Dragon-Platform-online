"""Model management uses the same app authorization and application DB boundary as report editing."""
import asyncio
from typing import Literal
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from app.core.response import success
from app.core.exceptions import BusinessError
from app.services import ai_models

router = APIRouter(prefix='/ai-models', tags=['ai-models'])


class Message(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(max_length=160000)


class Generate(BaseModel):
    config_id: str = Field(max_length=32)
    revision: str = Field(max_length=32)
    messages: list[Message] = Field(min_length=1, max_length=100)
    system: str = Field(default='', max_length=80000)
    max_tokens: int | None = Field(default=None, ge=1, le=131072)
    temperature: float | None = Field(default=None, ge=0, le=2)


async def connected(request, operation):
    """Stop upstream HTTP work when the browser disconnects. No retries or queued follow-up requests."""
    task = asyncio.create_task(operation)
    async def watch():
        while True:
            if await request.is_disconnected(): return
            await asyncio.sleep(0.1)
    watcher = asyncio.create_task(watch())
    try:
        done, _ = await asyncio.wait((task, watcher), return_when=asyncio.FIRST_COMPLETED)
        if task in done: return success(data=await task)
        raise BusinessError(499, '请求已停止')
    finally:
        for job in (task, watcher):
            if not job.done(): job.cancel()
        await asyncio.gather(task, watcher, return_exceptions=True)


@router.get('')
async def list_models(): return success(data=await ai_models.listing())


@router.post('/profiles')
async def save_model(payload: dict): return success(data=await ai_models.save(payload))


@router.delete('/profiles/{config_id}')
async def delete_model(config_id: str): return success(data=await ai_models.remove(config_id))


@router.post('/select')
async def select_model(payload: dict): return success(data=await ai_models.select(payload.get('mode'), payload.get('config_id', '')))


@router.post('/test')
async def test_model(payload: dict, request: Request): return await connected(request, ai_models.test_model(payload))


@router.post('/generate')
async def generate(payload: Generate, request: Request):
    if len(payload.system) + sum(len(m.content) for m in payload.messages) > 500000: raise BusinessError(400, '模型上下文超过 50 万字符，请新建会话')
    return await connected(request, ai_models.generate(payload))
