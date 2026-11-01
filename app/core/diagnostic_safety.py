"""Allowlisted diagnostic rendering. Never return raw responses or request headers."""
import re

def clean(value):
    text = str(value) if value is not None else ''
    text = re.sub(r'https?://[^\s<>"\']+', '[URL]', text, flags=re.I)
    text = re.sub(r'(?i)\bBearer\s+\S+', 'Bearer [REDACTED]', text)
    text = re.sub(r'(?i)(authorization|cookie|api[_-]?key|token|secret|password)["\s\x27:=]+[^\s,;}]+', r'\1=[REDACTED]', text)
    text = re.sub(r'\b(?:[A-Fa-f0-9]{48,}|sk-[A-Za-z0-9_-]{12,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b', '[REDACTED]', text)
    return text[:800]

def group_name(value):
    text = str(value or '')
    return clean(text) if re.fullmatch(r'[\w.\-\u4e00-\u9fff]{1,128}', text) else '[non-name value hidden]' if text else ''

def error_summary(body):
    if not isinstance(body, dict):
        return 'Non-JSON upstream response' if body is None else 'Unexpected upstream response type'
    parts = []
    for key in ('message', 'error', 'msg', 'detail'):
        value = body.get(key)
        if isinstance(value, str):
            parts.append(clean(value))
        elif key == 'detail' and isinstance(value, list):
            for item in value[:5]:
                if isinstance(item, dict):
                    parts.append(clean(str(item.get('loc', '')) + ': ' + str(item.get('msg', ''))))
    return '; '.join(parts)[:1200]
