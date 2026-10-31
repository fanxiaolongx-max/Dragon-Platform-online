"""基座运行期写接口契约：单条 DML，DDL 只由部署脚本执行。"""
import re
import os
from app.core.exceptions import QueryValidationError


def assert_host_contract() -> None:
    if os.getenv('PLATFORM_APP_SLUG') and os.getenv('PLATFORM_APP_DATABASE_CONTRACT') != 'digital-human':
        raise RuntimeError('当前平台未启用基座数据库契约，请先更新平台并重新导入本应用的平台包')


def _bare(sql: str, backslash_escapes: bool) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise QueryValidationError("SQL 不能为空")
    string = r"'(?:''|\\.|[^'\\])*'|\"(?:\"\"|\\.|[^\"\\])*\"" if backslash_escapes else r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\""
    tokens = string + r"|`(?:``|[^`])*`|/\*[\s\S]*?\*/|--[^\n]*|\#[^\n]*"
    bare = re.sub(tokens, lambda m: " " * len(m.group()), sql).strip()
    if bare.endswith(';'):
        bare = bare[:-1]
    if ';' in bare or "'" in bare or '"' in bare or '`' in bare:
        raise QueryValidationError("接口只允许一条完整 SQL")
    return bare


def assert_read_query(sql: str, *, backslash_escapes: bool = False) -> None:
    bare = _bare(sql, backslash_escapes)
    if not re.match(r"^(select|with)\b", bare, re.I) or re.search(r"\b(insert|update|delete|create|alter|drop|attach|detach|pragma|truncate)\b", bare, re.I):
        raise QueryValidationError("查询接口只读，不能写入或修改表结构")


def assert_app_write(sql: str, *, backslash_escapes: bool = False) -> None:
    bare = _bare(sql, backslash_escapes)
    kind = re.match(r"^(insert|update|delete)\b", bare, re.I)
    if not kind or re.search(r"\b(create|alter|drop|attach|detach|pragma|truncate)\b", bare, re.I):
        raise QueryValidationError("基座写接口只允许 INSERT / UPDATE / DELETE；DDL 请交 DBA 执行部署脚本")
    depth, where = 0, False
    for token in re.findall(r"\(|\)|\b\w+\b", bare):
        if token == '(':
            depth += 1
        elif token == ')':
            depth -= 1
        elif depth == 0 and token.lower() == 'where':
            where = True
    if kind[1].lower() in ('update', 'delete') and not where:
        raise QueryValidationError("UPDATE / DELETE 必须带 WHERE 条件")
