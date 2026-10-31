# -*- coding: utf-8 -*-
"""SQL工具函数"""

# MySQL（内网基座）默认把字符串里的反斜杠当转义符，SQLite（本地平台）不会；
# 由 app.db.detect_sql_dialect() 启动时探测后设置，写入代码、正则等含反斜杠的内容才不会被改坏。
BACKSLASH_ESCAPES = False


def set_backslash_escapes(enabled: bool) -> None:
    global BACKSLASH_ESCAPES
    BACKSLASH_ESCAPES = bool(enabled)


def format_sql_value(value):
    """
    将Python值格式化为SQL字面量

    Args:
        value: Python值

    Returns:
        str: SQL格式的值字符串

    处理规则:
        - None -> 'NULL' (不带引号)
        - bool -> 'TRUE'/'FALSE' (不带引号)
        - int/float -> 数字字符串(不带引号)
        - str -> 'value' (带单引号,内部单引号转义)
    """
    if value is None:
        return "NULL"
    elif isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    elif isinstance(value, (int, float)):
        return str(value)
    else:
        # 字符串类型,转义单引号并加引号
        escaped = str(value)
        if BACKSLASH_ESCAPES:
            escaped = escaped.replace("\\", "\\\\")
        escaped = escaped.replace("'", "''")
        return f"'{escaped}'"
