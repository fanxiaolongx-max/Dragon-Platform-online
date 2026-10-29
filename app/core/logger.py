# -*- coding: utf-8 -*-
"""日志配置 — loguru"""
import sys
from loguru import logger

# 移除默认handler
logger.remove()

# 添加控制台输出
logger.add(
    sys.stdout,
    format=("<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"),
    level="DEBUG",
)

# 添加文件输出（按天轮转）
logger.add(
    "logs/report_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="INFO",
)

__all__ = ["logger"]
