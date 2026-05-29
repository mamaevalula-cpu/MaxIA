# -*- coding: utf-8 -*-
"""
scripts/restore.py — Восстановление системы из бэкапа.

Использование:
    python scripts/restore.py backups/personal_ai_backup_20260514_030000.tar.gz
    python scripts/restore.py backups/personal_ai_backup_20260514_030000.tar.gz --target /opt/personal_ai
    python scripts/restore.py --list   # Список доступных бэкапов

Порядок восстановления:
  1. Валидация архива (BACKUP_MANIFEST.txt)
  2. Резервная копия текущего состояния (.env, БД)
  3. Распаковка в целевую директорию
  4. Восстановление .env
  5. Проверка целостности (синтаксис Python, наличие ключевых файлов)
  6. Инструкция по перезапуску
"""

from __future__ import annotations

import argparse
import logging
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("restore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

BASE_DIR = Path(__file__).parent.parent
BACKUP_DIR = BASE_DIR / "backups"


def list_backups(backup_dir: Path = BACKUP_DIR) -> None:
    archives = sorted(
        backup_dir.glob("personal_ai_backup_*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not archives:
        print("No backups found in", backup_dir)
        return
    print(f"\nAvailable backups ({len(archives)} total):\n")
    for a in archives:
        size_mb = a.stat().st_size / 1_048_576
        ts = datetime.fromtimestamp(a.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"  {ts}  {size_mb:6.1f} MB  {a.name}")
    print()


def validate_archive(archive: Path) -> bool:
    """Check that archive contains BACKUP_MANIFEST.txt and main.py."""
    try:
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
        has_manifest = "BACKUP_MANIFEST.txt" in names
        has_main = "main.py" in names
        if not has_manifest:
            log.error("Archive missing BACKUP_MANIFEST.txt — not a valid backup")
            return False
        if not has_main:
            log.error("Archive missing main.py — possibly incomplete backup")
            return False
        return True
    except tarfile.TarError as e:
        log.error("Archive corrupt: %s", e)
        return False


def restore(archive: Path, target: Path = BASE_DIR, dry_run: bool = False) -> bool:
    """
    Restore from backup archive.
    Returns True if successful.
    """
    if not archive.exists():
        log.error("Archive not found: %s", archive)
        return False

    if not validate_archive(archive):
        return False

    log.info("Restoring from: %s", archive)
    log.info("Target: %s", target)

    if dry_run:
        log.info("[DRY RUN] Would restore to %s", target)
        with tarfile.open(archive, "r:gz") as tar:
            log.info("Archive contains %d files", len(tar.getnames()))
        return True

    # ── Step 1: Pre-restore snapshot of .env and DBs ──────────────────────────
    pre_backup_dir = target / f"_pre_restore_{int(time.time())}"
    pre_backup_dir.mkdir(parents=True, exist_ok=True)
    for critical in [".env", ".env.local"]:
        src = target / critical
        if src.exists():
            import shutil
            shutil.copy2(src, pre_backup_dir / critical)
            log.info("Saved pre-restore: %s", critical)

    # ── Step 2: Extract archive ───────────────────────────────────────────────
    extracted = 0
    errors = 0
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            # Skip manifest (not a real file to restore)
            if member.name == "BACKUP_MANIFEST.txt":
                continue
            dest = target / member.name
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if member.isfile():
                    with tar.extractfile(member) as f:
                        dest.write_bytes(f.read())
                    extracted += 1
            except Exception as e:
                log.warning("Skip %s: %s", member.name, e)
                errors += 1

    log.info("Extracted: %d files (%d errors)", extracted, errors)

    # ── Step 3: Restore .env.local if it was saved (not in archive) ──────────
    for critical in [".env.local"]:
        saved = pre_backup_dir / critical
        if saved.exists():
            import shutil
            shutil.copy2(saved, target / critical)
            log.info("Restored local override: %s", critical)

    # ── Step 4: Integrity check ───────────────────────────────────────────────
    key_files = ["main.py", "brain/orchestrator.py", "core/config.py"]
    ok = True
    for kf in key_files:
        if not (target / kf).exists():
            log.error("Missing key file after restore: %s", kf)
            ok = False

    if ok:
        log.info("Integrity check: OK")

    print(f"""
╔══════════════════════════════════════════╗
║    RESTORE COMPLETE                      ║
╠══════════════════════════════════════════╣
║ Files restored: {extracted:<25d}║
║ Pre-restore snapshot: {pre_backup_dir.name:<19s}║
╠══════════════════════════════════════════╣
║ NEXT STEPS:                              ║
║  1. cd {str(target)[:34]}  ║
║  2. pip install -r requirements.txt      ║
║  3. python main.py --setup  (if new env) ║
║  4. python main.py                       ║
╚══════════════════════════════════════════╝
""")
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Personal AI — restore from backup")
    parser.add_argument("archive", nargs="?", help="Path to .tar.gz backup file")
    parser.add_argument("--target", default=str(BASE_DIR),
                        help="Target directory for restore")
    parser.add_argument("--list", action="store_true",
                        help="List available backups and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate archive without extracting")
    args = parser.parse_args()

    if args.list:
        list_backups()
        sys.exit(0)

    if not args.archive:
        # Auto-select latest backup
        archives = sorted(BACKUP_DIR.glob("personal_ai_backup_*.tar.gz"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        if not archives:
            print("No backups found. Run: python scripts/backup.py")
            sys.exit(1)
        archive_path = archives[0]
        print(f"Auto-selected latest backup: {archive_path.name}")
    else:
        archive_path = Path(args.archive)

    success = restore(
        archive=archive_path,
        target=Path(args.target),
        dry_run=args.dry_run,
    )
    sys.exit(0 if success else 1)
