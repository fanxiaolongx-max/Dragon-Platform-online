# -*- coding: utf-8 -*-
"""SQL工具函数"""


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
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"
