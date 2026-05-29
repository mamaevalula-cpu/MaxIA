# -*- coding: utf-8 -*-
"""
core/secret_manager.py — Зашифрованное хранилище секретов.

Использует Fernet (симметричное AES-128-CBC + HMAC-SHA256).
Ключ шифрования выводится из мастер-пароля через PBKDF2.
Хранилище: data/secrets.db (SQLite, зашифрованные значения).

Использование:
    sm = SecretManager.get("my_master_password")
    sm.set("bybit_api_key", "xxx")
    key = sm.get("bybit_api_key")
    sm.list_keys()
"""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

import logging
log = logging.getLogger("core.secrets")

_DB_PATH = Path(__file__).parent.parent / "data" / "secrets.db"
_SALT_FILE = Path(__file__).parent.parent / "data" / ".salt"


def _derive_key(password: str, salt: bytes) -> bytes:
    """Вывести 32-байтовый ключ из пароля через PBKDF2."""
    if not _CRYPTO_AVAILABLE:
        # Fallback: просто SHA-256 (небезопасно, но работает без cryptography)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return base64.urlsafe_b64encode(dk)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def _get_or_create_salt() -> bytes:
    _SALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _SALT_FILE.exists():
        return _SALT_FILE.read_bytes()
    salt = os.urandom(32)
    _SALT_FILE.write_bytes(salt)
    return salt


class SecretManager:
    """
    Зашифрованное хранилище ключей и паролей.
    Singleton с привязкой к мастер-паролю.
    """

    _instance: Optional["SecretManager"] = None
    _lock = threading.Lock()

    def __init__(self, master_password: str) -> None:
        self._db_path = _DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        salt = _get_or_create_salt()
        key = _derive_key(master_password, salt)

        if _CRYPTO_AVAILABLE:
            self._fernet = Fernet(key)
        else:
            self._fernet = None
            log.warning("cryptography not installed — secrets stored with XOR (insecure!)")

        self._key = key
        self._rlock = threading.RLock()
        self._init_db()
        log.info("SecretManager ready (db=%s, crypto=%s)", self._db_path, _CRYPTO_AVAILABLE)

    @classmethod
    def get(cls, master_password: str = "") -> "SecretManager":
        """Получить или создать экземпляр."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    if not master_password:
                        master_password = os.getenv("MASTER_PASSWORD", "default_insecure_key")
                    cls._instance = cls(master_password)
        return cls._instance

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS secrets (
                    key         TEXT PRIMARY KEY,
                    value_enc   BLOB NOT NULL,
                    service     TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    created_at  REAL NOT NULL,
                    updated_at  REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS auth_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    service     TEXT NOT NULL,
                    action      TEXT NOT NULL,
                    details     TEXT DEFAULT '',
                    ts          REAL NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path))

    # ── Шифрование ────────────────────────────────────────────────────────────

    def _encrypt(self, value: str) -> bytes:
        data = value.encode("utf-8")
        if self._fernet:
            return self._fernet.encrypt(data)
        # XOR-fallback (небезопасный)
        key_bytes = self._key[:len(data)] if len(self._key) >= len(data) else \
                    (self._key * (len(data) // len(self._key) + 1))[:len(data)]
        return bytes(a ^ b for a, b in zip(data, key_bytes))

    def _decrypt(self, enc: bytes) -> str:
        if self._fernet:
            try:
                return self._fernet.decrypt(enc).decode("utf-8")
            except Exception:
                raise ValueError("Неверный мастер-пароль или повреждённые данные")
        key_bytes = self._key[:len(enc)] if len(self._key) >= len(enc) else \
                    (self._key * (len(enc) // len(self._key) + 1))[:len(enc)]
        return bytes(a ^ b for a, b in zip(enc, key_bytes)).decode("utf-8")

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def set(self, key: str, value: str, service: str = "", description: str = "") -> None:
        """Сохранить секрет."""
        now = time.time()
        enc = self._encrypt(value)
        with self._rlock, self._connect() as conn:
            conn.execute("""
                INSERT INTO secrets (key, value_enc, service, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_enc=excluded.value_enc,
                    service=excluded.service,
                    description=excluded.description,
                    updated_at=excluded.updated_at
            """, (key, enc, service, description, now, now))
        log.info("Secret set: %s [service=%s]", key, service)

    def get(self, key: str, default: str = "") -> str:
        """Получить секрет. Возвращает default если не найден."""
        with self._rlock, self._connect() as conn:
            row = conn.execute(
                "SELECT value_enc FROM secrets WHERE key=?", (key,)
            ).fetchone()
        if not row:
            return default
        try:
            return self._decrypt(bytes(row[0]))
        except Exception as e:
            log.error("Failed to decrypt %s: %s", key, e)
            return default

    def delete(self, key: str) -> bool:
        with self._rlock, self._connect() as conn:
            cur = conn.execute("DELETE FROM secrets WHERE key=?", (key,))
            return cur.rowcount > 0

    def list_keys(self, service: str = "") -> List[Dict]:
        """Список ключей (без значений)."""
        with self._rlock, self._connect() as conn:
            if service:
                rows = conn.execute(
                    "SELECT key, service, description, updated_at FROM secrets WHERE service=?",
                    (service,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key, service, description, updated_at FROM secrets"
                ).fetchall()
        return [
            {"key": r[0], "service": r[1], "description": r[2], "updated_at": r[3]}
            for r in rows
        ]

    def exists(self, key: str) -> bool:
        with self._rlock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM secrets WHERE key=?", (key,)
            ).fetchone()
        return row is not None

    # ── Логирование действий с авторизацией ──────────────────────────────────

    def log_auth_action(self, service: str, action: str, details: str = "") -> None:
        """Записать действие авторизации в аудит-лог."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO auth_log (service, action, details, ts) VALUES (?,?,?,?)",
                (service, action, details, time.time())
            )

    def get_auth_log(self, service: str = "", limit: int = 50) -> List[Dict]:
        with self._connect() as conn:
            if service:
                rows = conn.execute(
                    "SELECT service,action,details,ts FROM auth_log WHERE service=? ORDER BY ts DESC LIMIT ?",
                    (service, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT service,action,details,ts FROM auth_log ORDER BY ts DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        return [{"service": r[0], "action": r[1], "details": r[2], "ts": r[3]} for r in rows]

    # ── Импорт из .env ────────────────────────────────────────────────────────

    def import_from_env(self, env_file: Path, service: str = "env") -> int:
        """Импортировать все переменные из .env в зашифрованное хранилище."""
        if not env_file.exists():
            return 0
        count = 0
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if value:
                self.set(key, value, service=service)
                count += 1
        log.info("Imported %d keys from %s", count, env_file)
        return count
