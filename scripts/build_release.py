#!/usr/bin/env python3
"""Build uploadable application ZIPs from tracked source, using only the stdlib."""
import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from urllib.parse import urlsplit
from uuid import UUID
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    ".env", "requirements.txt", "run.py", "AiOps-Report.version", "app/main.py",
    "static/shared/ai-diagnostics.js", "static/air/ai-backend.js", "static/air/trace.js", "static/air/tasks.js", "static/index.html", "static/air/default-template.json", "static/air/default-template.js", "static/air/default-logo.png", "db/init.sql", "db/init.sqlite.sql", "db/upgrade.sql", "db/upgrade.sqlite.sql",
}
TOP_FILES = {"requirements.txt", "run.py", "AiOps-Report.version", "README.md", ".env"}
SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules",
    "logs", "uploads", "backups", "tmp", "secrets", "credentials",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "__macosx",
}


def included(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"Unsafe source path: {name}")
    if any(part.lower() in SKIP_DIRS for part in path.parts):
        return False
    basename = path.name.lower()
    if (basename.startswith("._")
            or (basename.startswith(".env") and name != ".env")
            or basename in {".ds_store", "thumbs.db", "_platform_host.py"}
            or re.search(r"\.(py[co]|log|db|sqlite|sqlite3)(-(wal|shm|journal))?$", basename)
            or re.search(r"\.(pem|key|p12|pfx)$", basename)
            or re.match(r"(secrets?|credentials?|tokens?)(\.|$)", basename)):
        return False
    return (name in TOP_FILES or path.parts[0] in {"app", "static"}
            or name in {"db/init.sql", "db/init.sqlite.sql", "db/upgrade.sql", "db/upgrade.sqlite.sql"})



# This release includes connection/profile defaults only. Unknown keys (including credentials)
# stop packaging; comments are regenerated so pasted private notes never enter the ZIP.
ENV_KEYS = {
    'APP_NAME', 'DEBUG', 'PORT', 'WORKERS', 'RELOAD', 'CORS_ORIGINS',
    'BASE_QUERY_URL', 'BASE_EXECUTE_URL', 'BASE_DATASOURCES_URL', 'BASE_FIND_TABLE_URL', 'BASE_REP_OFFICES_URL',
    'APP_DATASOURCE_ID', 'APP_SCHEMA', 'APP_UUID', 'APP_LEVEL', 'INJECT_IDENTITY_HEADERS',
    'BUSINESS_DATASOURCE_NAME', 'HTTP_TIMEOUT', 'HTTP_VERIFY_SSL',
}

def checked_env(content):
    values = {}
    def fail(): raise ValueError('Release .env contains unsupported or unsafe configuration; values omitted')
    def valid_url(value):
        try:
            u = urlsplit(value)
            return u.scheme in ('http', 'https') and bool(u.hostname) and not (u.username or u.password or u.query or u.fragment) and all(ord(c) >= 32 for c in value)
        except ValueError: return False
    for line in content.decode('utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        match = re.fullmatch(r'([A-Z_][A-Z_0-9]*)\s*=\s*(.*)', line)
        if not match: fail()
        key, value = match.groups()
        if key not in ENV_KEYS or key in values: fail()
        if key != 'CORS_ORIGINS' and len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if any(c in value for c in ('\n', '\r', '\x00', '$', '`')): fail()
        if key.endswith('_URL'):
            if not valid_url(value): fail()
        elif key in ('APP_SCHEMA', 'APP_UUID'):
            try: UUID(value)
            except ValueError: fail()
        elif key in ('DEBUG', 'RELOAD', 'INJECT_IDENTITY_HEADERS', 'HTTP_VERIFY_SSL'):
            if value.lower() not in ('true', 'false', '1', '0'): fail()
        elif key in ('PORT', 'WORKERS', 'HTTP_TIMEOUT'):
            if not value.isdigit() or not 1 <= int(value) <= (65535 if key == 'PORT' else 1000): fail()
        elif key == 'APP_DATASOURCE_ID':
            if value != 'app' and not value.isdigit(): fail()
        elif key == 'APP_LEVEL':
            if value not in ('BASE', 'BUSINESS'): fail()
        elif key == 'CORS_ORIGINS':
            try: origins = json.loads(value)
            except ValueError: fail()
            if not isinstance(origins, list) or any(not isinstance(v, str) or (v != '*' and not valid_url(v)) for v in origins): fail()
        elif key in ('BUSINESS_DATASOURCE_NAME', 'APP_NAME'):
            if not re.fullmatch(r'[\w.\-\u4e00-\u9fff]{1,128}', value): fail()
        values[key] = value
    if not values.get('BUSINESS_DATASOURCE_NAME'): fail()
    return ('# Reviewed connection/profile defaults; target process environment has priority.\n'
            + ''.join(f'{key}={value}\n' for key, value in values.items())).encode()


def source_files(root):
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=root
    ).decode("utf-8").split("\0")
    files = {}
    for name in sorted(filter(None, tracked)):
        if not included(name):
            continue
        file = root / name
        if any(parent.is_symlink() for parent in [file, *file.parents] if parent != root):
            raise ValueError(f"Symbolic links cannot be packaged: {name}")
        content = file.read_bytes()
        files[name] = checked_env(content) if name == ".env" else content
    missing = REQUIRED - files.keys()
    if missing:
        raise ValueError(f"Missing required source: {', '.join(sorted(missing))}")
    return files


def write_zip(target, files):
    # Match Dragon Platform's importer limits for both packages.
    if len(files) > 3000 or sum(map(len, files.values())) > 300 * 1024 * 1024:
        raise ValueError("Application exceeds 3000 files or 300 MB unpacked")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    if target.stat().st_size > 35 * 1024 * 1024:
        target.unlink()
        raise ValueError("Application ZIP exceeds 35 MB")


def build(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    files = source_files(root)
    version = files["AiOps-Report.version"].decode().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version) or len(version) > 32:
        raise ValueError("AiOps-Report.version must contain a release version, e.g. 1.4.0")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    output.mkdir(parents=True, exist_ok=True)
    v_tag = f"v{version}" if not version.startswith("v") else version
    base_name = f"AiOps-Report-{v_tag}-base.zip"
    platform_name = f"AiOps-Report-{v_tag}-platform.zip"
    base = output / base_name
    platform = output / platform_name
    write_zip(base, files)
    manifest = {
        "name": "AiOps-Report", "version": version,
        "entry": "app.main:create_app", "factory": True,
        "interface": "asgi", "healthPath": "/health",
        "databaseContract": "digital-human",
    }
    write_zip(platform, {**files, "platform-app.json": (json.dumps(manifest, indent=2) + "\n").encode()})
    (output / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}\n"
        for file in [base, platform]
    ), encoding="utf-8")
    metadata = {
        "version": version,
        "commit": commit,
        "tag": f"build-v{version}-{commit[:12]}",
        "basePackage": base_name,
        "platformPackage": platform_name,
    }
    (output / "release.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    print(json.dumps(build(ROOT, args.output)))
