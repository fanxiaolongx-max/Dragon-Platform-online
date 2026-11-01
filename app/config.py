# -*- coding: utf-8 -*-
"""统一配置：通过环境变量或 .env 文件注入，代码中不出现硬连接信息。"""
import os
from functools import lru_cache
from typing import List
from pathlib import Path
from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_version() -> str:
    version_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "AiOps-Report.version")
    env = os.environ.get("APP_VERSION")
    if env:
        return env
    try:
        with open(version_file, "r", encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- 应用信息 ----
    APP_NAME: str = "AiOps-Report"
    APP_VERSION: str = _read_version()
    DEBUG: bool = True

    # ---- 运行 ----
    WORKERS: int = 1
    RELOAD: bool = False         # 基座由进程管理器启停；自动重载可能留下监听端口的子进程
    PORT: int = 5600              # 主服务端口

    # ---- CORS ----
    CORS_ORIGINS: List[str] = ["*"]

    # ---- 分页 ----
    MAX_PAGE_SIZE: int = 1000
    DEFAULT_PAGE_SIZE: int = 50

    # ---- 基座 API 配置（默认空串兜底，实际值由 .env 或基座环境变量注入） ----
    # 基座数据查询接口地址
    BASE_QUERY_URL: str = ""
    # 基座写操作接口地址
    BASE_EXECUTE_URL: str = ""
    # 基座数据源列表接口地址
    BASE_DATASOURCES_URL: str = ""
    # 基座按表名反查接口地址
    BASE_FIND_TABLE_URL: str = ""
    # 基座办事处列表接口地址
    BASE_REP_OFFICES_URL: str = ""
    # "应用数据库-自定义应用"数据源 ID
    APP_DATASOURCE_ID: int | str = 0
    # 应用专属 schema（即应用 UUID）
    APP_SCHEMA: str = ""
    # 应用 UUID
    APP_UUID: str = ""
    # 应用等级 BUSINESS / BASE
    APP_LEVEL: str = "BUSINESS"
    # 本地开发时手动注入写操作身份头（基座环境内由 sitecustomize.py 自动注入，无需开启）
    INJECT_IDENTITY_HEADERS: bool = False
    # 业务数据库组名
    BUSINESS_DATASOURCE_NAME: str = ""

    # ---- HTTP 客户端 ----
    HTTP_TIMEOUT: int = 15          # 调用基座 API 超时(秒)
    HTTP_VERIFY_SSL: bool = False  # 基座自签证书，关闭校验


_DIAGNOSTIC_FIELDS = ('BASE_QUERY_URL', 'APP_DATASOURCE_ID', 'APP_SCHEMA', 'BUSINESS_DATASOURCE_NAME', 'PORT', 'WORKERS', 'RELOAD')
def _environment_value(key):
    return next((value for name, value in reversed(list(os.environ.items())) if name.upper() == key), None)

_START_ENV = {key: _environment_value(key) for key in _DIAGNOSTIC_FIELDS}
try:
    _START_DOTENV = {key.upper(): value for key, value in dotenv_values(Path.cwd() / '.env').items() if key.upper() in _DIAGNOSTIC_FIELDS}
except (OSError, ValueError):
    _START_DOTENV = {}

def configuration_origins():
    """Only source labels and comparisons; never return environment/file contents."""
    def matches(value, loaded):
        if value is None: return None
        if isinstance(loaded, bool): return value.lower() in ('true', '1', 'yes', 'on') if loaded else value.lower() in ('false', '0', 'no', 'off')
        if isinstance(loaded, int):
            try: return int(value) == loaded
            except ValueError: return False
        return str(value) == str(loaded)
    return {key: {
        'source': 'process-environment' if _START_ENV[key] is not None else '.env' if _START_DOTENV.get(key) is not None else 'default',
        'environmentPresentAtLoad': _START_ENV[key] is not None,
        'dotenvContainsField': key in _START_DOTENV,
        'environmentChangedSinceLoad': _environment_value(key) != _START_ENV[key],
        'environmentMatchesLoaded': matches(_environment_value(key), getattr(settings, key)),
        'dotenvMatchesLoaded': matches(_START_DOTENV.get(key), getattr(settings, key)),
    } for key in _DIAGNOSTIC_FIELDS}

@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

def reload_profile(config):
    managed = bool(config.APP_UUID or config.APP_SCHEMA or os.getenv('PLATFORM_APP_SLUG'))
    return {'requested': config.RELOAD, 'managed': managed, 'enabled': config.RELOAD and not managed}
