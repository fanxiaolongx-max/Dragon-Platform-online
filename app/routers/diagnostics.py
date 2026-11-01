"""Whitelisted, read-only probes; never accept arbitrary SQL or database targets."""
from fastapi import APIRouter, Request
from app.core.response import success
from app.services import database_diagnostics as suite

router = APIRouter(prefix='/diagnostics/database', tags=['diagnostics'])

@router.get('')
async def manifest(table: str = '', full: bool = False):
    return success(data=suite.manifest(table, full))

@router.post('')
async def probe(request: Request):
    body = await request.json()
    return success(data=await suite.probe(str(body.get('id', '')), str(body.get('table', ''))))
