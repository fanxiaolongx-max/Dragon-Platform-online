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


_ROOT_DIR = Path(__file__).resolve().parents[1]

BETA_HOST = "netcareclaw-beta.icta138.huawei.com"
BETA_QUERY_URL = f"https://{BETA_HOST}/digital-human/api/dh/query"
BETA_SCHEMA = "eca61f00-e292-48ae-8767-c57826706e6a"

PROD_HOST = "netcareclaw.gde.huawei.com"
PROD_QUERY_URL = f"https://{PROD_HOST}/digital-human/api/dh/query"
PROD_SCHEMA = "cb6053a5-fdc9-4627-99ad-b3a5dc7bfbfa"

KNOWN_BASE_PROFILES = {
    "beta": {
        "name": "beta",
        "host": BETA_HOST,
        "query_url": BETA_QUERY_URL,
        "schema": BETA_SCHEMA,
    },
    "prod": {
        "name": "prod",
        "host": PROD_HOST,
        "query_url": PROD_QUERY_URL,
        "schema": PROD_SCHEMA,
    },
}

_BUSINESS_DATASOURCE_ALIASES = {
    "netcare-digital-human-readonly": "netcareClaw-operate-digital-readonly",
    "netcare-digital-human-business": "netcareClaw-operate-digital-readonly",
}

KNOWN_BUSINESS_DATASOURCES = (
    "netcareClaw-operate-digital-readonly",
    "netcareClaw-operate-digital-business",
    "netcare-digital-human-readonly",
    "netcare-digital-human-business",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ROOT_DIR / ".env"), extra="ignore")

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

    # Model encryption key is deployment-only: never include it in a release ZIP.
    AI_MODEL_ENCRYPTION_KEY: str = ""
    AI_MODEL_KEY_FILE: str = ""

    # ---- HTTP 客户端 ----
    HTTP_TIMEOUT: int = 15          # 调用基座 API 超时(秒)
    HTTP_VERIFY_SSL: bool = False  # 基座自签证书，关闭校验

    def model_post_init(self, __context) -> None:
        import sys
        if self.BUSINESS_DATASOURCE_NAME in _BUSINESS_DATASOURCE_ALIASES:
            self.BUSINESS_DATASOURCE_NAME = _BUSINESS_DATASOURCE_ALIASES[self.BUSINESS_DATASOURCE_NAME]

        env_url = (os.environ.get("BASE_QUERY_URL") or "").strip()
        env_schema = (os.environ.get("APP_SCHEMA") or "").strip()
        env_uuid = (os.environ.get("APP_UUID") or "").strip()
        env_inject = os.environ.get("INJECT_IDENTITY_HEADERS")

        # 1. 若进程环境变量或配置明确指向生产环境（域名或 UUID），自动对齐生产 URL 与 Schema/UUID
        is_prod_signal = (
            PROD_HOST in env_url
            or PROD_SCHEMA in (env_schema, env_uuid)
            or PROD_HOST in (self.BASE_QUERY_URL or "")
            or PROD_SCHEMA in (self.APP_SCHEMA, self.APP_UUID)
        )
        is_beta_signal = (
            BETA_HOST in env_url
            or BETA_SCHEMA in (env_schema, env_uuid)
        )

        if is_prod_signal and not is_beta_signal:
            if not env_url and (not self.BASE_QUERY_URL or BETA_HOST in self.BASE_QUERY_URL):
                self.BASE_QUERY_URL = PROD_QUERY_URL
            if not env_schema and not env_uuid:
                self.APP_SCHEMA = PROD_SCHEMA
                self.APP_UUID = PROD_SCHEMA
            elif env_schema and not env_uuid:
                self.APP_UUID = env_schema
            elif env_uuid and not env_schema:
                self.APP_SCHEMA = env_uuid
            elif self.APP_SCHEMA == BETA_SCHEMA:
                self.APP_SCHEMA = PROD_SCHEMA
                self.APP_UUID = PROD_SCHEMA
        elif is_beta_signal:
            if not env_url and (not self.BASE_QUERY_URL or PROD_HOST in self.BASE_QUERY_URL):
                self.BASE_QUERY_URL = BETA_QUERY_URL
            if not env_schema and not env_uuid:
                self.APP_SCHEMA = BETA_SCHEMA
                self.APP_UUID = BETA_SCHEMA

        # 2. 始终保持 APP_SCHEMA 与 APP_UUID 一致（基座内应用 Schema 即应用 UUID）
        if env_schema and not env_uuid:
            self.APP_UUID = self.APP_SCHEMA
        elif env_uuid and not env_schema:
            self.APP_SCHEMA = self.APP_UUID
        elif self.APP_SCHEMA and (not self.APP_UUID or self.APP_UUID != self.APP_SCHEMA):
            self.APP_UUID = self.APP_SCHEMA
        elif self.APP_UUID and not self.APP_SCHEMA:
            self.APP_SCHEMA = self.APP_UUID

        # 3. 真实基座容器内由进程环境变量注入配置且由 sitecustomize.py 自动注入身份头，避免 .env 的 INJECT_IDENTITY_HEADERS=true 冲突
        managed_base = bool(
            env_schema
            or env_url
            or os.environ.get("PLATFORM_DATA_API")
        )
        if managed_base and env_inject is None:
            self.INJECT_IDENTITY_HEADERS = False

    def apply_profile(self, profile_key: str, force: bool = False) -> str | None:
        """切换到指定基座环境档案（beta / prod），返回发生变更时的档案名。"""
        profile = KNOWN_BASE_PROFILES.get(profile_key)
        if not profile:
            return None
        target_schema = profile["schema"]
        target_url = profile["query_url"]
        other_key = "beta" if profile_key == "prod" else "prod"
        other_host = KNOWN_BASE_PROFILES[other_key]["host"]
        other_schema = KNOWN_BASE_PROFILES[other_key]["schema"]

        changed = False
        env_schema = (os.environ.get("APP_SCHEMA") or "").strip()
        env_url = (os.environ.get("BASE_QUERY_URL") or "").strip()

        if force or not env_schema or env_schema == other_schema:
            if self.APP_SCHEMA != target_schema or self.APP_UUID != target_schema:
                self.APP_SCHEMA = target_schema
                self.APP_UUID = target_schema
                changed = True

        if force or not env_url or other_host in env_url:
            if not self.BASE_QUERY_URL or other_host in self.BASE_QUERY_URL:
                if self.BASE_QUERY_URL != target_url:
                    self.BASE_QUERY_URL = target_url
                    changed = True

        return profile_key if changed else None


def adapt_settings_from_headers(headers) -> str | None:
    """根据请求头中的域名（Host / X-Forwarded-Host / Origin / Referer）自适应对齐测试/生产基座配置。"""
    if os.environ.get("PLATFORM_DATA_API"):
        return None
    from urllib.parse import urlsplit
    # Forwarded/actual host wins over an older cross-environment Origin or Referer.
    for key in ("x-forwarded-host", "host", "origin", "referer"):
        value = str(headers.get(key, "")).split(",", 1)[0].strip()
        if not value:
            continue
        try:
            host = (urlsplit(value if "://" in value else "//" + value).hostname or "").lower()
        except ValueError:
            continue
        if host == PROD_HOST:
            return settings.apply_profile("prod")
        if host == BETA_HOST:
            return settings.apply_profile("beta")
    return None


_DIAGNOSTIC_FIELDS = ('BASE_QUERY_URL', 'APP_DATASOURCE_ID', 'APP_SCHEMA', 'BUSINESS_DATASOURCE_NAME', 'PORT', 'WORKERS', 'RELOAD')
def _environment_value(key):
    return next((value for name, value in reversed(list(os.environ.items())) if name.upper() == key), None)

_START_ENV = {key: _environment_value(key) for key in _DIAGNOSTIC_FIELDS}
try:
    _dotenv_path = _ROOT_DIR / '.env'
    _START_DOTENV = {key.upper(): value for key, value in dotenv_values(_dotenv_path).items() if key.upper() in _DIAGNOSTIC_FIELDS}
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
