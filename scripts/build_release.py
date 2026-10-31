#!/usr/bin/env python3
"""Build uploadable application ZIPs from tracked source, using only the stdlib."""
import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "requirements.txt", "run.py", "AiOps-Report.version", "app/main.py",
    "static/index.html", "db/init.sql", "db/init.sqlite.sql", "db/upgrade.sql", "db/upgrade.sqlite.sql",
}
TOP_FILES = {"requirements.txt", "run.py", "AiOps-Report.version", "README.md"}
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
    if (basename.startswith((".env", "._"))
            or basename in {".ds_store", "thumbs.db", "_platform_host.py"}
            or re.search(r"\.(py[co]|log|db|sqlite|sqlite3)(-(wal|shm|journal))?$", basename)
            or re.search(r"\.(pem|key|p12|pfx)$", basename)
            or re.match(r"(secrets?|credentials?|tokens?)(\.|$)", basename)):
        return False
    return (name in TOP_FILES or path.parts[0] in {"app", "static"}
            or name in {"db/init.sql", "db/init.sqlite.sql", "db/upgrade.sql", "db/upgrade.sqlite.sql"})


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
        files[name] = file.read_bytes()
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
