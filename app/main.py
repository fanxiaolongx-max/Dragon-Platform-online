# -*- coding: utf-8 -*-
"""应用入口 - 运营数字人写报告服务"""
import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

from app.config import adapt_settings_from_headers, settings
from app.core.logger import logger
from app.core.exceptions import register_exception_handlers
from app.routers import health, report, data_element, data_source, data_query, table_map, agent, air, environment, diagnostics, ops
from app.routers import ai_models
from app import db
from app.db import close_client, detect_sql_dialect
from app.utils.sql_contract import assert_host_contract
from app.services import ops_service

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

    # CORS配置（同时兼容 .env 列表与沙箱/内网反代请求）
    cors_origins = list(settings.CORS_ORIGINS or [])
    if "*" not in cors_origins:
        cors_origins.append("*")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )

    app.middleware("http")(environment.guard)

    # 页面、脚本、样式每次向服务器核对（未变化时 304），更新应用后浏览器不会继续用缓存里的旧版本。
    @app.middleware("http")
    async def revalidate_static(request, call_next):
        switched = adapt_settings_from_headers(request.headers)
        if switched:
            db._dialect_checked = False
            logger.info(f"根据请求头域名自动对齐线上基座环境：{switched} (APP_SCHEMA={settings.APP_SCHEMA[:8]}...)")
        # 交互日志：记下这次请求来自哪个页面、哪个接口
        token = ops_service.request_context.set({
            "page": ops_service.page_of(request.headers.get("referer", ""), request.headers.get("x-ops-page", "")),
            "route": request.url.path[-200:],
        })
        try:
            response = await call_next(request)
        finally:
            ops_service.request_context.reset(token)
        path = request.url.path
        if request.method == "GET" and (path.endswith(("/", ".html", ".js", ".css")) or path in ("/dev", "/api-test")):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    # 注册路由（全部挂到根级 /api）
    app.include_router(ai_models.router, prefix="/api")
    app.include_router(health.router, prefix="/api")
    app.include_router(report.router, prefix="/api")
    app.include_router(data_element.router, prefix="/api")
    app.include_router(data_source.router, prefix="/api")
    app.include_router(data_query.router, prefix="/api")
    app.include_router(table_map.router, prefix="/api")
    app.include_router(agent.router, prefix="/api")
    app.include_router(air.router, prefix="/api")
    app.include_router(environment.router, prefix="/api")
    app.include_router(diagnostics.router, prefix="/api")
    app.include_router(ops.router, prefix="/api")
    ops_service.install()

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
        from app.services.database_diagnostics import configuration
        import json
        logger.info('AIOPS_RUNTIME ' + json.dumps(configuration(), ensure_ascii=False))
        if settings.RELOAD:
            logger.warning('配置请求了 RELOAD=true；run.py 在基座/托管身份下会禁用重载，生产配置建议同步改为 false')

    @app.on_event("shutdown")
    async def shutdown_event():
        try:
            await ops_service.flush()
        except Exception:
            pass
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
