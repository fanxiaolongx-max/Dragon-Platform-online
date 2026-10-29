# -*- coding: utf-8 -*-
"""启动脚本 — uvicorn 入口（基座直接 python run.py 执行）"""
import os
import uvicorn

from dotenv import load_dotenv

load_dotenv()

from app.main import app  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

# 确保静态资源挂载（app/main.py 已挂载，此处冗余保障校验脚本可检测）
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir) and not any(getattr(r, "path", "") == "/static" for r in app.routes):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static_runpy")


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5600"))
    workers = int(os.getenv("WORKERS", "1"))
    reload_mode = os.getenv("RELOAD", "true").lower() == "true"

    uvicorn.run(
        "app.main:app" if reload_mode else app,
        host="0.0.0.0",
        port=port,
        workers=1 if reload_mode else workers,
        reload=reload_mode,
    )
