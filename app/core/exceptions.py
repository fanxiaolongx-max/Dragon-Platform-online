# -*- coding: utf-8 -*-
"""业务异常体系 + 全局异常处理器注册"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class BusinessError(Exception):
    """业务异常基类"""
    def __init__(self, code: int = -1, message: str = "业务异常", data=None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


class NotFoundError(BusinessError):
    """资源不存在"""
    def __init__(self, message: str = "资源不存在"):
        super().__init__(code=404, message=message)


class QueryValidationError(BusinessError):
    """查询参数校验失败"""
    def __init__(self, message: str = "查询参数校验失败"):
        super().__init__(code=400, message=message)


class DataSourceError(BusinessError):
    """数据源访问异常"""
    def __init__(self, message: str = "数据源访问异常"):
        super().__init__(code=500, message=message)


class DatabaseError(BusinessError):
    """数据库访问异常"""
    def __init__(self, message: str = "数据库访问异常"):
        super().__init__(code=500, message=message)


def register_exception_handlers(app: FastAPI):
    """注册全局异常处理器"""

    @app.exception_handler(BusinessError)
    async def business_error_handler(request: Request, exc: BusinessError):
        return JSONResponse(
            status_code=200,
            content={"code": exc.code, "message": exc.message, "data": exc.data},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"code": -1, "message": f"服务器内部错误: {str(exc)}", "data": None},
        )
