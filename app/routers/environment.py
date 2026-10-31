"""Host-controlled data environment; real base deployments have no local switching surface."""
import os
import asyncio
from fastapi import APIRouter, Request
from app.core.exceptions import BusinessError
from app.core.response import success
from app import db

router=APIRouter(prefix='/environment',tags=['environment'])
_switching=False
_active=0
_switch_lock=asyncio.Lock()

async def profile():
    host=os.environ.get('PLATFORM_DATA_API','')
    if not host:
        return {'mode':'remote','switchable':False,'remoteReady':True,'deployment':'digital-human'}
    response=await db._get_client().get(host+'/environment')
    try:body=response.json()
    except ValueError:raise BusinessError(409,'平台环境接口不可用，请先更新平台后端并重启 PM2')
    if response.status_code==404:raise BusinessError(409,'请先更新平台后端并重启 PM2，当前版本尚未支持统一数据环境')
    if body.get('code')!=0:raise BusinessError(body.get('code',500),body.get('message','环境状态读取失败'))
    return body['data']

@router.get('')
async def read_environment():
    return success(data=await profile())

@router.post('')
async def change_environment(request:Request):
    global _switching
    host=os.environ.get('PLATFORM_DATA_API','')
    if not host:raise BusinessError(403,'真实基座部署固定使用远端环境')
    async with _switch_lock:
        if _active:raise BusinessError(409,'当前有数据操作未完成，请等待保存或查询结束后再切换')
        _switching=True
        try:
            body=await request.json()
            headers={k:v for k,v in request.headers.items() if k.startswith('x-platform-')}
            response=await db._get_client().post(host+'/environment',json={'mode':body.get('mode')},headers=headers)
            result=response.json()
            if result.get('code')!=0:raise BusinessError(result.get('code',500),result.get('message','切换失败'))
            db._dialect_checked=False
            return success(data=result['data'])
        finally:
            _switching=False

async def guard(request:Request,call_next):
    global _active
    if not request.url.path.startswith('/api/') or request.url.path.startswith('/api/environment'):
        return await call_next(request)
    from fastapi.responses import JSONResponse
    async with _switch_lock:
        if _switching:
            return JSONResponse({'code':409,'message':'正在切换数据环境，请稍后重试','data':None})
        if os.environ.get('PLATFORM_DATA_API'):
            try:p=await profile()
            except BusinessError as error:return JSONResponse({'code':error.code,'message':error.message,'data':None})
            revision=request.headers.get('x-aiops-environment-revision')
            if str(p.get('revision',0)) != str(revision or '0'):
                return JSONResponse({'code':409,'message':'数据环境已切换，请刷新页面后再操作，防止写入错误的环境','data':None})
        _active+=1
    try:return await call_next(request)
    finally:_active-=1
