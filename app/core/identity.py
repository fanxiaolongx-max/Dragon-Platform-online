# -*- coding: utf-8 -*-
"""平台转发的当前用户身份，用来按团队隔离月报。

应用被平台「开放给全员」后，所有团队共用这一个进程和同一个应用库。平台在每个请求上附带：
  X-Platform-User / X-Platform-Role / X-Platform-Tenant（应用所在空间）/ X-Platform-User-Tenant（用户所属团队）
  X-Platform-Timestamp / X-Platform-Team-Signature = HMAC-SHA256(PLATFORM_APP_SECRET, user\\nrole\\ntenant\\nuserTenant\\ntimestamp)

- 官方身份（official）：用户所属团队就是应用所在空间，即平台超级管理员空间里的用户。可看、可改全部月报。
- 团队成员（member）：其它团队的账号。只能看官方月报和本团队的月报，只能改本团队的；不能碰应用的公共配置。
- 没有团队头（部署在数字人基座，或旧版平台）：不做隔离，行为与之前一致。
"""
import hashlib
import hmac
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote

from app.core.exceptions import BusinessError

MAX_SKEW_MS = 5 * 60 * 1000


@dataclass(frozen=True)
class Viewer:
    user: str
    team: str
    official: bool


_viewer: ContextVar[Optional[Viewer]] = ContextVar("platform_viewer", default=None)


class IdentityError(Exception):
    """团队头存在但签名不对：拒绝请求，而不是退回到不隔离。"""


def from_headers(headers) -> Optional[Viewer]:
    team = headers.get("x-platform-user-tenant")
    if team is None:
        return None
    secret = os.environ.get("PLATFORM_APP_SECRET", "")
    user, role = headers.get("x-platform-user", ""), headers.get("x-platform-role", "")
    tenant, stamp = headers.get("x-platform-tenant", ""), headers.get("x-platform-timestamp", "")
    expected = hmac.new(secret.encode(), f"{user}\n{role}\n{tenant}\n{team}\n{stamp}".encode(), hashlib.sha256).hexdigest()
    try:
        fresh = abs(time.time() * 1000 - int(stamp)) <= MAX_SKEW_MS
    except ValueError:
        fresh = False
    if not secret or not team or not fresh or not hmac.compare_digest(expected, headers.get("x-platform-team-signature", "")):
        raise IdentityError("平台身份校验失败，请从平台重新打开应用")
    return Viewer(user=unquote(user), team=team, official=team == tenant)


def current() -> Optional[Viewer]:
    return _viewer.get()


def set_current(viewer: Optional[Viewer]):
    return _viewer.set(viewer)


def reset(token) -> None:
    _viewer.reset(token)


def is_member() -> bool:
    viewer = _viewer.get()
    return bool(viewer and not viewer.official)


def deny_member(what: str = "该操作") -> None:
    """公共配置、应用库直查等只给官方身份。"""
    if is_member():
        raise BusinessError(403, f"{what}仅超级管理员可用")


# 团队成员不可用的接口：通用报告表读写、他人的交互日志、调试台、公共配置的修改
_MEMBER_DENY_ANY = ("/api/reports", "/api/dev-workspace", "/api/diagnostics", "/dev", "/dev.html", "/api-test", "/docs", "/redoc", "/openapi.json")
_MEMBER_DENY_WRITE = ("/api/data-elements", "/api/data-sources", "/api/ai-models/profiles", "/api/ai-models/select", "/api/ops/tables")


def member_blocked(method: str, path: str) -> bool:
    hit = lambda prefixes: any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)
    if hit(_MEMBER_DENY_ANY):
        return True
    if method == "GET" and (path == "/api/ops/logs" or path.startswith("/api/ops/logs/")):
        return True
    return method not in ("GET", "HEAD", "OPTIONS") and hit(_MEMBER_DENY_WRITE)
