# -*- coding: utf-8 -*-
"""
launch.py — Загрузчик системы my_personal_ai.

Запуск:
  pythonw.exe launch.py   → GUI без консоли (ярлык на рабочем столе)
  python.exe   launch.py   → GUI с консолью (для отладки)
  python.exe   launch.py --no-gui → headless (CLI)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Пути — ПЕРВЫМ ДЕЛОМ ───────────────────────────────────────────────────────
LAUNCH_DIR = Path(__file__).resolve().parent   # my_personal_ai/
BYBIT_DIR  = LAUNCH_DIR.parent / "bybit-bot"

# PYTHONPATH через os.environ (работает даже без батника)
_paths = [str(LAUNCH_DIR), str(BYBIT_DIR)]
os.environ["PYTHONPATH"] = os.pathsep.join(
    _paths + [os.environ.get("PYTHONPATH", "")]
).strip(os.pathsep)

if str(LAUNCH_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCH_DIR))
if BYBIT_DIR.exists() and str(BYBIT_DIR) not in sys.path:
    sys.path.append(str(BYBIT_DIR))

os.chdir(LAUNCH_DIR)

# ── Кодировка (только если есть консоль) ─────────────────────────────────────
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    import io
    # pythonw.exe → stdout/stderr = None, пропускаем
    if sys.stdout is not None and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace")
    if sys.stderr is not None and hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

# При pythonw.exe stdout = None — перенаправим в лог-файл
if sys.stdout is None:
    log_path = LAUNCH_DIR / "logs" / "launch.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _logf = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = _logf
        sys.stderr = _logf
    except Exception:
        import io as _io
        sys.stdout = _io.StringIO()
        sys.stderr = sys.stdout

# ── Загрузка .env ─────────────────────────────────────────────────────────────
def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        # .env.local — наивысший приоритет (локальные переопределения)
        env_local = LAUNCH_DIR / ".env.local"
        if env_local.exists():
            load_dotenv(env_local, override=True)
        # .env — стандартный файл конфигурации
        env_file = LAUNCH_DIR / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
        # bybit-bot/.env — вторичный источник (не перекрывает основной)
        bybit_env = BYBIT_DIR / ".env"
        if bybit_env.exists():
            load_dotenv(bybit_env, override=False)
    except ImportError:
        pass

_load_env()

# ── Точка входа ───────────────────────────────────────────────────────────────
def run() -> None:
    no_gui      = "--no-gui"      in sys.argv or "--headless" in sys.argv
    no_telegram = "--no-telegram" in sys.argv

    # Всегда пишем ошибки в лог — даже если нет консоли (pythonw)
    _err_log = LAUNCH_DIR / "logs" / "startup_err.log"
    _err_log.parent.mkdir(parents=True, exist_ok=True)

    try:
        from main import main
        main(no_gui=no_gui, no_telegram=no_telegram)
    except Exception:
        # Записываем полный traceback в лог
        import traceback
        tb = traceback.format_exc()
        # Всегда сохраняем в файл (работает даже с pythonw)
        try:
            with open(_err_log, "a", encoding="utf-8") as _f:
                _f.write(f"\n{'='*60}\n{tb}\n")
        except Exception:
            pass
        try:
            print(tb, flush=True)
        except Exception:
            pass
        # Показываем окно с ошибкой (чтобы пользователь увидел)
        try:
            import tkinter as tk
            from tkinter import messagebox
            _r = tk.Tk(); _r.withdraw()
            _r.attributes("-topmost", True)
            messagebox.showerror(
                "Personal AI — Ошибка запуска",
                f"Не удалось запустить систему:\n\n{tb[-1200:]}\n\n"
                f"Подробности: {_err_log}"
            )
            _r.destroy()
        except Exception:
            pass

if __name__ == "__main__":
    run()
