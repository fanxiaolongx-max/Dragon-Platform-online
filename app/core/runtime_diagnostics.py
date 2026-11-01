"""Identifies the process that really serves a request, without exposing machine credentials."""
import hashlib
import os
import time
import uuid
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from app.config import settings, reload_profile, KNOWN_BASE_PROFILES
from urllib.parse import urlsplit

BOOT_ID = str(uuid.uuid4())
STARTED_AT = datetime.now(timezone.utc).isoformat()
STARTED_MONOTONIC = time.monotonic()

def _fingerprint():
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for name in ('run.py', 'app/config.py', 'app/db.py', 'app/services/database_diagnostics.py'):
        digest.update(name.encode()); digest.update((root / name).read_bytes())
    return digest.hexdigest()[:16]

CODE_FINGERPRINT = _fingerprint()

def active_profile():
    if os.environ.get('PLATFORM_DATA_API'): return 'platform-managed'
    try: host = urlsplit(settings.BASE_QUERY_URL).hostname
    except ValueError: return 'unknown'
    return next((key for key, value in KNOWN_BASE_PROFILES.items() if value['host'] == host), 'custom' if host else 'unconfigured')

def snapshot():
    version = (Path(__file__).resolve().parents[2] / 'AiOps-Report.version').read_text().strip()
    return {'bootId': BOOT_ID, 'pid': os.getpid(), 'parentPid': os.getppid(), 'startedAt': STARTED_AT,
            'uptimeSeconds': round(time.monotonic() - STARTED_MONOTONIC), 'listenPort': settings.PORT,
            'activeBaseProfile': active_profile(), 'reloadEnabled': reload_profile(settings)['enabled'], 'reloadRequested': settings.RELOAD,
            'managedRuntime': reload_profile(settings)['managed'], 'workerCount': settings.WORKERS, 'codeFingerprint': CODE_FINGERPRINT,
            'pythonVersion': platform.python_version(), 'packageVersion': version if re.fullmatch(r'\d+\.\d+\.\d+', version) else 'unknown'}
