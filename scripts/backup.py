# -*- coding: utf-8 -*-
"""
scripts/backup.py — Ежедневный компактный бэкап системы.

Создаёт .tar.gz архив со всем необходимым для полного восстановления:
  - Весь код (Python, конфиги, скрипты)
  - .env (без .env.local — там локальные секреты)
  - SQLite базы (memory, vector store, family bus, task queue)
  - memory/ директория (lessons, RAG data)
  - logs/ (последние 7 дней)
  - Исключает: __pycache__, .pyc, venv, node_modules, *.bak.*

Запуск:
    python scripts/backup.py                 # бэкап в backups/
    python scripts/backup.py --dest /mnt/backup  # другой путь
    python scripts/backup.py --remote user@host:/path  # + scp на сервер

Интеграция с watchdog:
    Зарегистрируй в server_launcher.py или cron:
    0 3 * * * /usr/bin/python3 /path/to/scripts/backup.py >> /var/log/backup.log 2>&1
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("backup")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

BASE_DIR = Path(__file__).parent.parent
BACKUP_DIR = BASE_DIR / "backups"

# Что включить в архив
INCLUDE_DIRS = [
    "brain", "core", "agents", "gui", "memory", "monitoring",
    "family", "training", "validation", "compliance", "polishing",
    "cleaner", "browser_agent", "auth", "vector_stores",
    "scripts", "data",
]
INCLUDE_FILES = [
    "main.py", "launch.py", "run_headless.py", "server_launcher.py",
    "server_dashboard.py", "init_production.py",
    ".env",         # API ключи — включаем т.к. нужны для восстановления
    "requirements.txt",
]
INCLUDE_DB_PATTERNS = [
    "**/*.db", "**/*.sqlite", "**/*.sqlite3",
]
MEMORY_DIRS = [
    "memory_store", "memory",
]

# Что исключить из архива
EXCLUDE_PATTERNS = [
    "__pycache__", "*.pyc", "*.pyo", "*.pyd",
    "*.bak.*", ".git", "venv", ".venv", "env",
    "node_modules", "*.egg-info", ".pytest_cache",
    "backups",  # не включаем старые бэкапы
    "logs",     # логи опциональны — добавим только последние
]

KEEP_BACKUPS = 7  # Хранить бэкапы за последние 7 дней


def _should_exclude(path: Path) -> bool:
    for part in path.parts:
        for pattern in ("__pycache__", ".git", "venv", ".venv", "node_modules",
                        ".pytest_cache", "backups"):
            if part == pattern:
                return True
    name = path.name
    for pattern in ("*.pyc", "*.pyo", "*.pyd", "*.bak.*"):
        import fnmatch
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _add_dir(tar: tarfile.TarFile, src: Path, arcbase: str) -> int:
    """Recursively add directory to tar, skipping excluded paths."""
    added = 0
    if not src.exists():
        return 0
    for item in src.rglob("*"):
        if _should_exclude(item):
            continue
        arcname = arcbase + "/" + str(item.relative_to(src.parent))
        try:
            tar.add(item, arcname=arcname, recursive=False)
            added += 1
        except (OSError, PermissionError):
            pass
    return added


def create_backup(dest_dir: Path = BACKUP_DIR, remote: str = "") -> Path:
    """
    Create a compressed backup archive.
    Returns path to the created .tar.gz file.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"personal_ai_backup_{ts}.tar.gz"
    archive_path = dest_dir / archive_name

    log.info("Starting backup → %s", archive_path)
    t0 = time.time()
    file_count = 0

    with tarfile.open(archive_path, "w:gz", compresslevel=6) as tar:
        # ── Code directories ──────────────────────────────────────────────────
        for dir_name in INCLUDE_DIRS:
            src = BASE_DIR / dir_name
            if src.exists():
                n = _add_dir(tar, src, dir_name)
                file_count += n
                log.info("  + %s/  (%d files)", dir_name, n)

        # ── Root files ────────────────────────────────────────────────────────
        for fname in INCLUDE_FILES:
            src = BASE_DIR / fname
            if src.exists():
                tar.add(src, arcname=fname)
                file_count += 1
                log.info("  + %s", fname)

        # ── SQLite databases ──────────────────────────────────────────────────
        for pattern in INCLUDE_DB_PATTERNS:
            for db_file in BASE_DIR.rglob(pattern):
                if _should_exclude(db_file):
                    continue
                # Skip databases already covered by directory includes
                rel = db_file.relative_to(BASE_DIR)
                if str(rel.parts[0]) in INCLUDE_DIRS:
                    continue
                arcname = str(rel)
                try:
                    tar.add(db_file, arcname=arcname)
                    file_count += 1
                    log.info("  + %s (db)", arcname)
                except Exception:
                    pass

        # ── Recent logs (last 7 days) ─────────────────────────────────────────
        logs_dir = BASE_DIR / "logs"
        if logs_dir.exists():
            cutoff = time.time() - 7 * 86400
            n = 0
            for log_file in logs_dir.glob("*.log"):
                try:
                    if log_file.stat().st_mtime > cutoff:
                        tar.add(log_file, arcname=f"logs/{log_file.name}")
                        n += 1
                except Exception:
                    pass
            log.info("  + logs/  (%d recent files)", n)
            file_count += n

        # ── Memory / lessons ─────────────────────────────────────────────────
        memory_dir = BASE_DIR / "memory"
        if memory_dir.exists():
            for f in memory_dir.glob("*.json"):
                try:
                    tar.add(f, arcname=f"memory/{f.name}")
                    file_count += 1
                except Exception:
                    pass

        # ── BACKUP MANIFEST ───────────────────────────────────────────────────
        manifest = (
            f"backup_timestamp: {ts}\n"
            f"source: {BASE_DIR}\n"
            f"files: {file_count}\n"
            f"created_by: scripts/backup.py\n"
        )
        import io
        manifest_bytes = manifest.encode("utf-8")
        info = tarfile.TarInfo(name="BACKUP_MANIFEST.txt")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

    size_mb = archive_path.stat().st_size / 1_048_576
    elapsed = time.time() - t0
    log.info("Backup complete: %d files, %.1f MB, %.1fs", file_count, size_mb, elapsed)

    # ── SCP to remote ─────────────────────────────────────────────────────────
    if remote:
        _scp_to_remote(archive_path, remote)

    # ── Rotate old backups ────────────────────────────────────────────────────
    _rotate_backups(dest_dir)

    return archive_path


def _scp_to_remote(archive: Path, remote: str) -> None:
    """Copy backup to remote server via scp."""
    log.info("Copying to remote: %s", remote)
    try:
        result = subprocess.run(
            ["scp", "-o", "StrictHostKeyChecking=no", str(archive), remote],
            timeout=300, capture_output=True, text=True,
        )
        if result.returncode == 0:
            log.info("Remote copy OK")
        else:
            log.error("scp failed: %s", result.stderr)
    except FileNotFoundError:
        log.warning("scp not found — skipping remote copy")
    except subprocess.TimeoutExpired:
        log.error("scp timeout (>5min) — backup not transferred")
    except Exception as e:
        log.error("Remote copy error: %s", e)


def _rotate_backups(backup_dir: Path, keep: int = KEEP_BACKUPS) -> None:
    """Delete oldest backups, keep only the last N."""
    archives = sorted(
        backup_dir.glob("personal_ai_backup_*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
    )
    to_delete = archives[:-keep] if len(archives) > keep else []
    for old in to_delete:
        try:
            old.unlink()
            log.info("Deleted old backup: %s", old.name)
        except Exception:
            pass


def scheduled_backup_hook() -> None:
    """
    Call this from server_launcher.py daily loop or systemd timer.
    Reads BACKUP_DEST and BACKUP_REMOTE from environment.
    """
    dest = Path(os.environ.get("BACKUP_DEST", str(BACKUP_DIR)))
    remote = os.environ.get("BACKUP_REMOTE", "")
    try:
        path = create_backup(dest_dir=dest, remote=remote)
        log.info("Scheduled backup created: %s", path)
    except Exception as e:
        log.error("Scheduled backup FAILED: %s", e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Personal AI — daily backup")
    parser.add_argument("--dest", default=str(BACKUP_DIR),
                        help="Destination directory for backup archives")
    parser.add_argument("--remote", default="",
                        help="SCP destination: user@host:/path/to/backup/")
    parser.add_argument("--keep", type=int, default=KEEP_BACKUPS,
                        help="Number of backups to retain")
    args = parser.parse_args()

    archive = create_backup(
        dest_dir=Path(args.dest),
        remote=args.remote,
    )
    print(f"\n✅ Backup: {archive}")
    print(f"   Size:   {archive.stat().st_size / 1_048_576:.1f} MB")
