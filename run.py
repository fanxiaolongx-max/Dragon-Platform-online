# -*- coding: utf-8 -*-
"""启动脚本 — uvicorn 入口（基座直接 python run.py 执行）"""
import os
import json
import uvicorn

from app.config import settings, reload_profile
from app.main import app  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

# 确保静态资源挂载（app/main.py 已挂载，此处冗余保障校验脚本可检测）
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir) and not any(getattr(r, "path", "") == "/static" for r in app.routes):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static_runpy")


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


def server_options():
    """One settings source; development watchers never include the virtual environment."""
    reload_enabled = reload_profile(settings)['enabled']
    options = dict(host='0.0.0.0', port=settings.PORT, workers=1 if reload_enabled else max(1, settings.WORKERS), reload=reload_enabled)
    if reload_enabled:
        options.update(reload_dirs=[os.path.join(os.path.dirname(__file__), 'app')], reload_excludes=['venv/*', '.venv/*', '__pycache__/*'])
    return options

def main():
    from app.core.logger import logger
    from app.services.database_diagnostics import configuration
    from app.core.runtime_diagnostics import snapshot
    logger.info('AIOPS_LAUNCH ' + json.dumps(configuration(), ensure_ascii=False))
    try:
        uvicorn.run('app.main:app', **server_options())
    except SystemExit as error:
        logger.error('AIOPS_LAUNCH_EXIT ' + json.dumps({'exitCode': error.code, 'runtime': snapshot()}, ensure_ascii=False))
        raise

if __name__ == "__main__":
    main()
