import asyncio
import os
import unittest
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from app.routers import environment as env
from app import db
from app.core.exceptions import register_exception_handlers

class EnvironmentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_client=db._client
        self.old_lock=env._switch_lock
        env._switch_lock=asyncio.Lock();env._active=0;env._switching=False
        self.revision=0
        def host(request):
            if request.method=='POST':self.revision+=1
            return httpx.Response(200,json={'code':0,'data':{'mode':'local','revision':self.revision,'switchable':True}})
        db._client=httpx.AsyncClient(transport=httpx.MockTransport(host))
        app=FastAPI();register_exception_handlers(app);app.middleware('http')(env.guard);app.include_router(env.router,prefix='/api')
        self.entered,self.release=asyncio.Event(),asyncio.Event()
        @app.get('/api/operation')
        async def operation():
            self.entered.set();await self.release.wait();return {'code':0}
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture')
    async def asyncTearDown(self):
        await self.client.aclose();await db._client.aclose();db._client=self.old_client;env._switch_lock=self.old_lock
    async def test_native_base_locks_remote_and_refuses_local_switch(self):
        with patch.dict(os.environ):
            os.environ.pop('PLATFORM_DATA_API',None)
            profile=(await self.client.get('/api/environment')).json()['data']
            self.assertEqual(profile['mode'],'remote');self.assertFalse(profile['switchable'])
            self.assertEqual((await self.client.post('/api/environment',json={'mode':'local'})).json()['code'],403)
    async def test_switch_waits_for_data_operations_and_stale_tabs_cannot_use_new_environment(self):
        with patch.dict(os.environ,{'PLATFORM_DATA_API':'http://host.fixture/dh'}):
            operation=asyncio.create_task(self.client.get('/api/operation',headers={'x-aiops-environment-revision':'0'}))
            await self.entered.wait()
            self.assertEqual((await self.client.post('/api/environment',json={'mode':'remote'})).json()['code'],409)
            self.assertEqual(self.revision,0)
            self.release.set();await operation
            self.assertEqual((await self.client.post('/api/environment',json={'mode':'remote'})).json()['code'],0)
            stale=(await self.client.get('/api/operation',headers={'x-aiops-environment-revision':'0'})).json()
            self.assertEqual(stale['code'],409)
            self.assertEqual((await self.client.get('/api/operation',headers={'x-aiops-environment-revision':'1'})).json()['code'],0)
