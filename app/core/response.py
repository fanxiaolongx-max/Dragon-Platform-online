# -*- coding: utf-8 -*-
"""统一响应体"""
from typing import Any, Optional


def success(data: Any = None, message: str = "success", total: Optional[int] = None) -> dict:
    """成功响应"""
    result = {
        "code": 0,
        "message": message,
        "data": data,
    }
    if total is not None:
        result["total"] = total
    return result


def error(code: int = -1, message: str = "error", data: Any = None) -> dict:
    """错误响应"""
    return {
        "code": code,
        "message": message,
        "data": data,
    }
