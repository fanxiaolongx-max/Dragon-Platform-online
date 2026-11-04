"""Application-scoped model profiles. Credentials never leave the server in read APIs."""
import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app import db
from app.config import settings
from app.core.exceptions import BusinessError, DatabaseError
from app.core.logger import logger
from app.utils.sql_helper import format_sql_value as lit

PROTOCOLS = ('openai', 'responses', 'anthropic', 'gemini', 'ollama', 'custom')
PUBLIC = ('name', 'protocol', 'base_url', 'model', 'auth_type', 'auth_header', 'timeout',
          'max_tokens', 'temperature', 'verify_ssl', 'response_path')
PRIVATE = ('api_key', 'headers', 'extra_body', 'body_template')
_lock = asyncio.Lock()


def cipher():
    """Use a deployment secret, or a per-application private file outside the ZIP."""
    key = settings.AI_MODEL_ENCRYPTION_KEY.strip()
    if not key:
        identity = settings.APP_UUID or settings.APP_SCHEMA or 'standalone'
        suffix = hashlib.sha256(identity.encode()).hexdigest()[:24]
        path = Path(settings.AI_MODEL_KEY_FILE).expanduser() if settings.AI_MODEL_KEY_FILE else Path.home() / '.aiops-report' / 'keys' / (suffix + '.key')
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            # Atomic create/rename: other workers must never observe a partially written key.
            if not path.exists():
                import tempfile
                fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.key-')
                try:
                    with os.fdopen(fd, 'wb') as handle:
                        handle.write(Fernet.generate_key())
                        handle.flush()
                        os.fsync(handle.fileno())
                    try: os.link(temp, path)
                    except FileExistsError: pass
                finally: os.unlink(temp)
            if path.is_symlink() or path.stat().st_mode & 0o077:
                raise OSError('key file permissions')
            key = path.read_text().strip()
        except OSError:
            raise BusinessError(503, '无法安全读取模型加密主密钥；请配置 AI_MODEL_ENCRYPTION_KEY 或可持久化的 AI_MODEL_KEY_FILE') from None
    try: return Fernet(key.encode())
    except (ValueError, TypeError):
        raise BusinessError(503, '模型加密主密钥无效，请配置 Fernet 格式的 AI_MODEL_ENCRYPTION_KEY') from None


def decode(row):
    try:
        return json.loads(cipher().decrypt(row['config_cipher'].encode()))
    except (InvalidToken, ValueError, KeyError):
        raise BusinessError(409, '无法解密模型配置，请恢复原加密主密钥；不要删除密钥文件或覆盖原配置') from None


def public(row, config):
    return {'id': row['id'], 'revision': row['revision'], **{k: config.get(k) for k in PUBLIC},
            **{'has_' + k: bool(config.get(k)) for k in PRIVATE}}


async def row_for(config_id):
    if not re.fullmatch(r'[a-f0-9]{32}', str(config_id)):
        raise BusinessError(400, '模型配置 ID 无效')
    rows = await db.query_app_schema(f'SELECT * FROM t_ai_model_config WHERE id={lit(config_id)}', limit=1)
    if not rows: raise BusinessError(404, '模型配置不存在')
    return rows[0]


def missing_table(error, table):
    text = str(error).lower()
    return table in text and any(word in text for word in ("doesn't exist", 'does not exist', 'no such table', '不存在', 'unknown table'))


async def listing():
    # An older installation can keep using ADC before applying the new feature's DDL.
    # Only the proven absence of BOTH new tables permits that default; other DB errors remain errors.
    try:
        return await _listing()
    except DatabaseError as error:
        if not missing_table(error, 't_ai_model_config'): raise
        try:
            await db.query_app_schema("SELECT id FROM t_ai_model_state WHERE id='active'", limit=1)
        except DatabaseError as state_error:
            if missing_table(state_error, 't_ai_model_state'):
                return {'mode': 'adc', 'config_id': '', 'items': [], 'protocols': list(PROTOCOLS), 'migration_required': True}
            raise
        raise


async def _listing():
    rows = await db.query_app_schema('SELECT * FROM t_ai_model_config ORDER BY updated_at DESC, id', limit=200)
    selected = await db.query_app_schema("SELECT * FROM t_ai_model_state WHERE id='active'", limit=1)
    state = selected[0] if selected else {'mode': 'adc', 'config_id': ''}
    # A wrong/lost key must remain visible, without returning ciphertext or secrets.
    items = []
    for row in rows:
        try: items.append(public(row, decode(row)))
        except BusinessError:
            items.append({'id': row['id'], 'revision': row['revision'], 'name': '无法解密的模型配置', 'locked': True})
    return {'mode': state['mode'], 'config_id': state['config_id'], 'items': items, 'protocols': list(PROTOCOLS)}


def validate(payload, previous=None):
    previous = previous or {}
    c = {**previous, **{k: v for k, v in payload.items() if k in PUBLIC}}
    for k in PRIVATE:
        # An empty password/advanced field means keep the stored value. Explicit empty objects clear JSON fields.
        if k in payload and payload[k] not in (None, ''): c[k] = payload[k]
        else: c[k] = previous.get(k, '' if k == 'api_key' else {})
    if payload.get('clear_api_key'): c['api_key'] = ''
    c['name'] = str(c.get('name') or '').strip()[:100]
    c['protocol'] = c.get('protocol', 'openai')
    if not c['name'] or c['protocol'] not in PROTOCOLS: raise BusinessError(400, '请填写配置名称并选择支持的协议')
    url = str(c.get('base_url') or '').strip().rstrip('/')
    try:
        u = urlsplit(url)
        valid = u.scheme in ('http', 'https') and u.hostname and not (u.username or u.password or u.fragment) and u.port != 0
        valid = valid and not re.search(r'[\s\x00-\x1f\x7f]', url) and len(url) <= 2048
        valid = valid and not any(re.search(r'key|token|secret|password|auth', k, re.I) for k, _ in parse_qsl(u.query))
    except ValueError: valid = False
    if not valid: raise BusinessError(400, '模型地址须为 HTTP/HTTPS，不得在 URL 中填写密钥、账号密码或片段')
    c['base_url'], c['model'] = url, str(c.get('model') or '').strip()[:200]
    if not c['model'] and c['protocol'] != 'custom': raise BusinessError(400, '请填写模型名称')
    c['auth_type'] = c.get('auth_type') or ('none' if c['protocol'] == 'ollama' else 'x-api-key' if c['protocol'] == 'anthropic' else 'x-goog-api-key' if c['protocol'] == 'gemini' else 'bearer')
    if c['auth_type'] not in ('none', 'bearer', 'x-api-key', 'api-key', 'x-goog-api-key', 'custom'): raise BusinessError(400, '认证方式无效')
    c['auth_header'] = str(c.get('auth_header') or '').strip()
    if c['auth_type'] == 'custom' and not re.fullmatch(r'[A-Za-z0-9-]{1,80}', c['auth_header']): raise BusinessError(400, '自定义认证头名称无效')
    c['api_key'] = str(c['api_key'])
    if len(c['api_key']) > 8192 or re.search(r'[\r\n\x00]', c['api_key']): raise BusinessError(400, 'API Key 格式无效')
    for k in ('headers', 'extra_body', 'body_template'):
        if not isinstance(c[k], dict) or len(json.dumps(c[k])) > 60000: raise BusinessError(400, k + ' 必须是 JSON 对象（最多 60 KB）')
    forbidden = {'host', 'content-length', 'transfer-encoding', 'connection', 'cookie', 'proxy-authorization'}
    for k, v in c['headers'].items():
        if not re.fullmatch(r'[A-Za-z0-9-]{1,80}', k) or k.lower() in forbidden or not isinstance(v, str) or re.search(r'[\r\n\x00]', v): raise BusinessError(400, '附加请求头无效')
    if c['auth_header'].lower() in forbidden: raise BusinessError(400, '认证头名称不可使用此请求头')
    try:
        c['timeout'] = int(c.get('timeout', 120))
        c['max_tokens'] = int(c.get('max_tokens', 8000))
        c['temperature'] = float(c.get('temperature', 0.2))
        if not 5 <= c['timeout'] <= 600 or not 1 <= c['max_tokens'] <= 131072 or not 0 <= c['temperature'] <= 2: raise ValueError()
    except (TypeError, ValueError): raise BusinessError(400, '超时须为 5–600 秒，输出上限须为 1–131072，温度须为 0–2') from None
    if not isinstance(c.get('verify_ssl', True), bool): raise BusinessError(400, 'verify_ssl 必须为布尔值')
    c['verify_ssl'] = c.get('verify_ssl', True)
    c['response_path'] = str(c.get('response_path') or 'choices.0.message.content')
    if not re.fullmatch(r'[\w.]{1,200}', c['response_path']): raise BusinessError(400, '响应路径只能包含点、数字、下划线和字段名')
    if c['protocol'] == 'custom' and not c['body_template']: raise BusinessError(400, '自定义协议需要 JSON 请求模板')
    return c


async def save(payload):
    async with _lock:
        old = await row_for(payload['id']) if payload.get('id') else None
        if old and payload.get('revision') != old['revision']: raise BusinessError(409, '配置已被其他页面修改，请重新加载')
        c = validate(payload, decode(old) if old else None)
        config_id, revision = (old['id'] if old else uuid.uuid4().hex), uuid.uuid4().hex
        encrypted = cipher().encrypt(json.dumps(c, ensure_ascii=False).encode()).decode()
        now = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
        if old:
            affected = await db.execute_app_schema(f'UPDATE t_ai_model_config SET config_cipher={lit(encrypted)},revision={lit(revision)},updated_at={lit(now)} WHERE id={lit(config_id)} AND revision={lit(old["revision"])}')
            if not affected: raise BusinessError(409, '配置已更新，请重新加载')
        else:
            if len(await db.query_app_schema('SELECT id FROM t_ai_model_config', limit=200)) >= 100: raise BusinessError(400, '最多保存 100 个模型配置')
            await db.execute_app_schema(f'INSERT INTO t_ai_model_config (id,config_cipher,revision,updated_at) VALUES ({lit(config_id)},{lit(encrypted)},{lit(revision)},{lit(now)})')
        return public({'id': config_id, 'revision': revision}, c)


async def select(mode, config_id=''):
    if mode not in ('adc', 'model'): raise BusinessError(400, '模型通道无效')
    async with _lock:
        if mode == 'model': decode(await row_for(config_id))
        else: config_id = ''
        rows = await db.query_app_schema("SELECT id FROM t_ai_model_state WHERE id='active'", limit=1)
        if rows: await db.execute_app_schema(f"UPDATE t_ai_model_state SET mode={lit(mode)},config_id={lit(config_id)} WHERE id='active'")
        else: await db.execute_app_schema(f"INSERT INTO t_ai_model_state(id,mode,config_id) VALUES('active',{lit(mode)},{lit(config_id)})")
    return {'mode': mode, 'config_id': config_id}


async def remove(config_id):
    async with _lock:
        await row_for(config_id)
        state = await db.query_app_schema("SELECT config_id,mode FROM t_ai_model_state WHERE id='active'", limit=1)
        if state and state[0]['mode'] == 'model' and state[0]['config_id'] == config_id: raise BusinessError(409, '请先切换到 ADC 或其他模型，再删除当前模型')
        await db.execute_app_schema(f'DELETE FROM t_ai_model_config WHERE id={lit(config_id)}')
    return {'deleted': True}


def endpoint(base, suffix):
    # Accept either an API root or a full inference URL; retain harmless query parameters, e.g. api-version.
    u = urlsplit(base)
    path = u.path.rstrip('/')
    if not path.endswith(suffix): path += suffix
    return u._replace(path=path).geturl()


def template(value, variables):
    if isinstance(value, dict): return {k: template(v, variables) for k, v in value.items()}
    if isinstance(value, list): return [template(v, variables) for v in value]
    if isinstance(value, str):
        if value in variables: return variables[value]
        for key, replacement in variables.items():
            if isinstance(replacement, (str, int, float)): value = value.replace(key, str(replacement))
    return value


def wire(c, messages, system='', max_tokens=None, temperature=None):
    p, model = c['protocol'], c['model']
    root = c['base_url']
    if not urlsplit(root).path.strip('/') and p in ('openai', 'responses', 'anthropic', 'gemini'):
        root = endpoint(root, '/v1beta' if p == 'gemini' else '/v1')
    n = min(c['max_tokens'], max(1, int(max_tokens or c['max_tokens'])))
    t = c['temperature'] if temperature is None else float(temperature)
    headers = httpx.Headers({'Content-Type': 'application/json', **c['headers']})
    key, auth = c['api_key'], c['auth_type']
    if key and auth != 'none': headers['Authorization' if auth == 'bearer' else c['auth_header'] if auth == 'custom' else auth] = 'Bearer ' + key if auth == 'bearer' else key
    chat = ([{'role': 'system', 'content': system}] if system else []) + messages
    body = {'model': model, 'messages': chat, 'stream': False, 'max_tokens': n, 'temperature': t}
    if p == 'openai': url = endpoint(root, '/chat/completions')
    elif p == 'responses':
        url = endpoint(root, '/responses')
        body = {'model': model, 'input': messages, 'instructions': system, 'max_output_tokens': n, 'temperature': t, 'store': False, 'stream': False}
    elif p == 'anthropic':
        url = endpoint(root, '/messages')
        headers.setdefault('anthropic-version', '2023-06-01')
        body = {'model': model, 'messages': messages, 'system': system, 'max_tokens': n, 'temperature': t, 'stream': False}
    elif p == 'gemini':
        url = root if urlsplit(root).path.endswith(':generateContent') else endpoint(root, '/models/' + quote(model.removeprefix('models/'), safe='') + ':generateContent')
        body = {'contents': [{'role': 'model' if m['role'] == 'assistant' else 'user', 'parts': [{'text': m['content']}]} for m in messages], 'generationConfig': {'maxOutputTokens': n, 'temperature': t}}
        if system: body['systemInstruction'] = {'parts': [{'text': system}]}
    elif p == 'ollama':
        url = endpoint(root, '/chat' if urlsplit(c['base_url']).path.rstrip('/').endswith('/api') else '/api/chat')
        body = {'model': model, 'messages': chat, 'stream': False, 'options': {'num_predict': n, 'temperature': t}}
    else:
        url = c['base_url']
        body = template(c['body_template'], {'${messages}': chat, '${prompt}': messages[-1]['content'], '${system}': system, '${model}': model, '${max_tokens}': n, '${temperature}': t})
    body.update(c['extra_body'])
    body = {k: v for k, v in body.items() if v is not None}
    # Streaming and provider-side tools are intentionally not delegated: the app executes only its assigned DB tools.
    if p not in ('gemini', 'custom'): body['stream'] = False
    if any(k in body for k in ('tools', 'tool_choice', 'functions', 'function_call', 'previous_response_id', 'conversation', 'web_search_options')):
        raise BusinessError(400, '附加参数不可启用外部工具或服务端会话；数据工具统一由本应用执行')
    return url, headers, body


def strip_reasoning(text: str) -> str:
    """剥离模型正文中的思考过程标签（如 <think>...</think>）"""
    if not text:
        return ''
    cleaned = re.sub(r'<\s*think(?:ing)?\b[^>]*>[\s\S]*?<\s*/\s*think(?:ing)?\s*>', '', text, flags=re.I)
    if '<think' in cleaned.lower():
        cleaned = re.sub(r'<\s*think(?:ing)?\b[^>]*>[\s\S]*$', '', cleaned, flags=re.I)
    return cleaned.strip()


def extract(c, data):
    p = c['protocol']
    if p == 'responses':
        return ''.join(str(part.get('text', '')) for item in data.get('output', []) if item.get('type') == 'message' for part in item.get('content', []) if part.get('type') == 'output_text')
    if p == 'anthropic': return ''.join(str(x.get('text', '')) for x in data.get('content', []) if x.get('type') == 'text')
    if p == 'gemini': return ''.join(str(x.get('text', '')) for x in (data.get('candidates') or [{}])[0].get('content', {}).get('parts', []) if not x.get('thought'))
    if p == 'ollama': return str(data.get('message', {}).get('content') or '')

    # 自定义协议按照用户指定的响应路径提取
    if p == 'custom' and c.get('response_path'):
        value = data
        for part in c['response_path'].split('.'):
            value = value[int(part)] if isinstance(value, list) and part.isdigit() else value[part]
        if isinstance(value, list): return ''.join(str(x.get('text', '')) for x in value if isinstance(x, dict))
        return value if isinstance(value, str) else ''

    # OpenAI / 通用兼容协议多层自适应提取（兼容 Qwen3 / DeepSeek 思考模式与各类模型网关）
    if isinstance(data, dict):
        # 1. 错误拦截：某些国产网关在 HTTP 200 下返回业务错误 JSON
        if 'error' in data and data['error']:
            err = data['error']
            raise BusinessError(502, '模型服务返回业务错误，请联系模型服务管理员核对请求编号')
        if data.get('code') and data.get('code') not in (0, 200, '0', '200') and data.get('message'):
            raise BusinessError(502, '模型服务返回业务错误，请联系模型服务管理员核对请求编号')

        choices = data.get('choices')
        if isinstance(choices, list) and len(choices) > 0:
            first = choices[0] if isinstance(choices[0], dict) else {}
            msg = first.get('message') if isinstance(first.get('message'), dict) else {}

            # 标准 content 提取
            content = msg.get('content')
            if content is not None:
                if isinstance(content, str) and content.strip():
                    return strip_reasoning(content)
                if isinstance(content, list):
                    joined = ''.join(str(x.get('text', '')) if isinstance(x, dict) else str(x) for x in content)
                    if joined.strip(): return strip_reasoning(joined)

            # 思考模式兼容：当 content 为空或 null 时，回退提取 reasoning_content / reasoning / thought
            for rk in ('reasoning_content', 'reasoning', 'thought'):
                r_val = msg.get(rk)
                if isinstance(r_val, str) and r_val.strip():
                    logger.info(f"[MODEL-INVOKE] message.content 为空，从 {rk} 提取正文（长度 {len(r_val)}）")
                    return strip_reasoning(r_val)

            # completions 接口兼容（choices[0].text）
            if isinstance(first.get('text'), str) and first['text'].strip():
                return strip_reasoning(first['text'])

            # delta 流式片段兼容
            delta = first.get('delta') if isinstance(first.get('delta'), dict) else {}
            if isinstance(delta.get('content'), str) and delta['content'].strip():
                return strip_reasoning(delta['content'])

        # DashScope / 通义原生 output 结构兼容
        output = data.get('output')
        if isinstance(output, dict):
            if isinstance(output.get('text'), str) and output['text'].strip():
                return strip_reasoning(output['text'])
            o_choices = output.get('choices')
            if isinstance(o_choices, list) and len(o_choices) > 0:
                first = o_choices[0] if isinstance(o_choices[0], dict) else {}
                msg = first.get('message') if isinstance(first.get('message'), dict) else {}
                if isinstance(msg.get('content'), str) and msg['content'].strip():
                    return strip_reasoning(msg['content'])

        # 顶层通用字段兜底
        for k in ('text', 'response', 'answer', 'result'):
            if isinstance(data.get(k), str) and data[k].strip():
                return strip_reasoning(data[k])

    return ''


def response_json(raw, protocol):
    """Some OpenAI gateways return SSE even with stream=false. Never treat HTML as model text."""
    text = raw.decode('utf-8-sig').strip()
    try:
        data = json.loads(text)
    except ValueError:
        if protocol != 'openai' or not any(line.startswith('data:') for line in text.splitlines()):
            raise BusinessError(502, '模型服务返回空响应' if not text else '模型服务返回非 JSON 响应（可能是网关错误页），请检查模型服务和代理') from None
        data = {'choices': [{'message': {'content': '', 'reasoning_content': ''}, 'finish_reason': None}]}
        choice = data['choices'][0]
        events, done = 0, False
        # SSE permits comments, event names and multi-line data, with blank-line event boundaries.
        for frame in re.split(r'\r?\n\r?\n', text):
            payload = '\n'.join(line[5:].lstrip(' ') for line in frame.splitlines() if line.startswith('data:'))
            if not payload: continue
            if payload == '[DONE]':
                done = True
                break
            try: event = json.loads(payload)
            except ValueError: raise BusinessError(502, '模型流式响应包含无效 JSON，请检查模型网关') from None
            if not isinstance(event, dict): raise BusinessError(502, '模型流式响应结构无效')
            events += 1
            if event.get('error') or event.get('code') not in (None, 0, 200, '0', '200'):
                raise BusinessError(502, '模型流式服务返回业务错误，请联系模型服务管理员核对请求编号')
            if event.get('usage'): data['usage'] = event['usage']
            choices = event.get('choices') or []
            if not isinstance(choices, list): raise BusinessError(502, '模型流式响应结构无效')
            for part in choices:
                if not isinstance(part, dict): raise BusinessError(502, '模型流式响应结构无效')
                if part.get('index', 0) != 0: continue
                delta = part.get('delta') or part.get('message') or {}
                if not isinstance(delta, dict): raise BusinessError(502, '模型流式响应结构无效')
                for key in ('content', 'reasoning_content'):
                    value = delta.get(key)
                    if isinstance(value, list): value = ''.join(x.get('text', '') for x in value if isinstance(x, dict) and isinstance(x.get('text'), str))
                    if isinstance(value, str): choice['message'][key] += value
                if part.get('finish_reason'): choice['finish_reason'] = part['finish_reason']
        if not events or not (done or choice['finish_reason']):
            raise BusinessError(502, '模型流式响应提前中断，未收到完成标记，请重试')
    if not isinstance(data, dict): raise BusinessError(502, '模型响应须为 JSON 对象，请检查协议和响应路径')
    return data


async def invoke(c, messages, system='', max_tokens=None, temperature=None):
    url, headers, body = wire(c, messages, system, max_tokens, temperature)
    started, request_id = time.monotonic(), uuid.uuid4().hex

    # Only allowlisted transport metadata: headers, bodies and provider errors can echo credentials.
    diagnostic = {'kind': 'model_transport', 'requestId': request_id, 'protocol': c['protocol']}
    limits = {key: body[key] for key in ('max_tokens', 'max_completion_tokens', 'max_output_tokens')
              if type(body.get(key)) is int}
    if limits: diagnostic['outputLimits'] = limits
    logger.info(f"[MODEL-INVOKE] request_id={request_id} protocol={c['protocol']}")

    try:
        # Dedicated client: do not inherit the base client's identity headers, cookies, TLS policy, or retries.
        async with httpx.AsyncClient(timeout=c['timeout'], verify=c['verify_ssl'], trust_env=False, follow_redirects=False) as client:
            async with client.stream('POST', url, headers=headers, json=body) as r:
                media_type = r.headers.get('content-type', '').split(';')[0].strip().lower()
                if not re.fullmatch(r'[a-z0-9.+-]+/[a-z0-9.+-]+', media_type): media_type = 'unknown'
                diagnostic.update(upstreamStatus=r.status_code, contentType=media_type)
                chunks, size = [], 0
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    diagnostic['responseBytes'] = size
                    if size > 4 * 1024 * 1024: raise BusinessError(502, '模型响应超过 4 MB 上限')
                    chunks.append(chunk)
                status = r.status_code
                diagnostic['responseBytes'] = size
                if status < 200 or status >= 300:
                    hint = {401: '认证失败，请检查 API Key 和认证方式', 403: '无权调用此模型', 404: '模型或接口路径不存在', 429: '模型限流或额度不足'}.get(status, '模型服务返回错误')
                    raise BusinessError(status, hint + f'（HTTP {status}）')
                data = response_json(b''.join(chunks), c['protocol'])

        # ── 日志：响应阶段 ──
        ended = time.monotonic()
        total_ms = round((ended - started) * 1000)
        logger.info(f"[MODEL-INVOKE] response request_id={request_id} status={status} elapsed_ms={total_ms} content_type={media_type} bytes={size}")
        text = extract(c, data)

        # Reject incomplete responses instead of saving truncated recipes as successful results.
        _trunc_status = data.get('status') in ('failed', 'incomplete')
        _trunc_stop = data.get('stop_reason') == 'max_tokens'
        _trunc_choices = any(x.get('finish_reason') == 'length' for x in data.get('choices', []))
        _trunc_gemini = any(x.get('finishReason') == 'MAX_TOKENS' for x in data.get('candidates', []))
        truncated = _trunc_status or _trunc_stop or _trunc_choices or _trunc_gemini
        logger.info(f"[MODEL-INVOKE] truncation check: status_hit={_trunc_status} stop_hit={_trunc_stop} choices_hit={_trunc_choices} gemini_hit={_trunc_gemini} => truncated={truncated}")

        if truncated:
            # 容错降级：如果模型实际已经输出了合法的完整 JSON 响应（仅末尾空白或说明被截断），则宽容放行避免 502
            salvaged = False
            raw_text = text.strip()
            if raw_text:
                candidate = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw_text).strip()
                start = candidate.find('{')
                if start >= 0:
                    depth, in_str, esc = 0, False, False
                    for idx in range(start, len(candidate)):
                        ch = candidate[idx]
                        if in_str:
                            if esc: esc = False
                            elif ch == '\\': esc = True
                            elif ch == '"': in_str = False
                            continue
                        if ch == '"': in_str = True
                        elif ch == '{': depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                try:
                                    parsed = json.loads(candidate[start:idx + 1])
                                    if isinstance(parsed, dict) and any(k in parsed for k in ('type', 'conflict', 'recipe', 'question', 'text', 'tools', 'zh')):
                                        text = candidate[start:idx + 1]
                                        salvaged = True
                                        logger.warning(f"模型命中 finish_reason=length，但成功提取出完整 JSON 结构（保留 {len(text)} 字符）")
                                except Exception:
                                    pass
                                break
            if not salvaged:
                raise BusinessError(502, '模型输出达到上限被截断（单次生成触达模型物理上下文或输出上限）。已在提示词端精简上下文，请重试；若依然出现，请在模型服务部署参数中调大 --max-model-len')

        if not text.strip(): raise BusinessError(502, '模型未返回可读取的正文，请检查协议、响应路径或模型拒绝原因')
        for secret in [c['api_key'], *c['headers'].values()]:
            if secret: text = text.replace(secret, '[REDACTED]')

        usage = data.get('usage') or data.get('usageMetadata') or {}
        comp_tokens = (
            usage.get('completion_tokens')
            or usage.get('output_tokens')
            or usage.get('candidatesTokenCount')
        )
        if comp_tokens is None and total_ms > 0 and text:
            comp_tokens = max(1, round(len(text) / 1.8))
        tps = round(comp_tokens / (total_ms / 1000), 1) if comp_tokens and total_ms > 0 else None
        logger.info(f"[MODEL-INVOKE] total_ms={total_ms} comp_tokens={comp_tokens} tps={tps}")

        return {
            'text': text,
            'ms': total_ms,
            'request_id': request_id,
            'protocol': c['protocol'],
            'model': c['model'],
            'usage': usage,
            'tps': tps
        }
    except (httpx.RequestError, BusinessError, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        if isinstance(exc, BusinessError): code, message = exc.code, exc.message
        elif isinstance(exc, httpx.TimeoutException): code, message = 504, '模型请求超时，未自动重试；请检查模型服务或提高超时设置'
        elif isinstance(exc, httpx.RequestError): code, message = 502, '无法连接模型服务，请检查地址、HTTP/HTTPS、网络及证书设置'
        else: code, message = 502, '模型返回格式与所选协议不匹配，请检查协议和响应路径'
        diagnostic['ms'] = round((time.monotonic() - started) * 1000)
        logger.warning(f"[MODEL-INVOKE] failed {json.dumps(diagnostic)} code={code}")
        raise BusinessError(code, message + f'（请求编号 {request_id}）', diagnostic) from None


async def generate(payload):
    row = await row_for(payload.config_id)
    if row['revision'] != payload.revision: raise BusinessError(409, '模型配置已变化，本次操作已停止，请重试')
    return await invoke(decode(row), [m.model_dump() for m in payload.messages], payload.system, payload.max_tokens, payload.temperature)


async def test_model(payload):
    row = await row_for(payload['id']) if payload.get('id') else None
    if row and payload.get('revision') != row['revision']: raise BusinessError(409, '模型配置已变化，请重新加载')
    c = validate(payload, decode(row) if row else None)
    reply = await invoke(c, [{'role': 'user', 'content': 'Reply with OK only.'}], max_tokens=64, temperature=0)
    return {**reply, 'text': reply['text'][:200]}
