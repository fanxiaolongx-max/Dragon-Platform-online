# -*- coding: utf-8 -*-
"""应用入口 - 运营数字人写报告服务"""
import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

from app.config import settings
from app.core.logger import logger
from app.core.exceptions import register_exception_handlers
from app.routers import health, report, data_element, data_source, data_query, table_map, agent, air
from app.db import close_client, detect_sql_dialect
from app.utils.sql_contract import assert_host_contract

logging.getLogger("uvicorn").setLevel(logging.INFO)

# 静态文件目录
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


def create_app() -> FastAPI:
    """创建FastAPI应用实例"""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc"
    )

    # 注册异常处理器
    register_exception_handlers(app)

    # CORS配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )

    # 注册路由（全部挂到根级 /api）
    app.include_router(health.router, prefix="/api")
    app.include_router(report.router, prefix="/api")
    app.include_router(data_element.router, prefix="/api")
    app.include_router(data_source.router, prefix="/api")
    app.include_router(data_query.router, prefix="/api")
    app.include_router(table_map.router, prefix="/api")
    app.include_router(agent.router, prefix="/api")
    app.include_router(air.router, prefix="/api")

    # 挂载静态文件目录（基座要求 static/ 可访问）
    if os.path.isdir(STATIC_DIR):
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
        for sub in ("css", "js", "vendor", "air", "shared"):
            sub_dir = os.path.join(STATIC_DIR, sub)
            if os.path.isdir(sub_dir):
                app.mount(f"/{sub}", StaticFiles(directory=sub_dir), name=sub)

    # 健康检查接口（基座 HTTP 探测路径 /health，返回 200~399 即存活）
    @app.get("/health", include_in_schema=False)
    async def health_probe():
        return {"status": "healthy"}

    # 启动事件
    @app.on_event("startup")
    async def startup_event():
        assert_host_contract()
        await detect_sql_dialect()
        logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION} 启动完成")

    @app.on_event("shutdown")
    async def shutdown_event():
        await close_client()
        logger.info(f"{settings.APP_NAME} 已关闭，基座客户端连接已释放")

    # 主页：AI 月报；开发者模式：API 调试台（数据链路 / 源表直查 / 接口调试）
    index_file = os.path.join(STATIC_DIR, "index.html")
    dev_file = os.path.join(STATIC_DIR, "dev.html")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/index.html", response_class=HTMLResponse, include_in_schema=False)
    async def root():
        return FileResponse(index_file)

    @app.get("/dev", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/dev.html", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/api-test", response_class=HTMLResponse, include_in_schema=False)
    async def dev_page():
        return FileResponse(dev_file)

    return app


app = create_app()
