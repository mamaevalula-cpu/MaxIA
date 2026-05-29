# -*- coding: utf-8 -*-
"""
splash.pyw — Загрузочный экран Personal AI.
Открывается мгновенно, запускает main в фоне, закрывается когда GUI готов.
"""
import sys, os, threading
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
sys.path.append(str(BASE.parent / "bybit-bot"))
os.chdir(BASE)

# Перенаправляем вывод в лог (pythonw.exe)
if sys.stdout is None:
    _lf = open(BASE / "logs" / "launch.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = _lf
    sys.stderr = _lf

# ── Splash окно (открывается за < 0.5 сек) ───────────────────────────────────
import tkinter as tk
from tkinter import ttk

splash = tk.Tk()
splash.title("Personal AI")
splash.geometry("420x200")
splash.resizable(False, False)
splash.configure(bg="#1a1a2e")
splash.attributes("-topmost", True)

# Центрируем окно
splash.update_idletasks()
w = splash.winfo_screenwidth()
h = splash.winfo_screenheight()
x = (w - 420) // 2
y = (h - 200) // 2
splash.geometry(f"420x200+{x}+{y}")

# Контент
tk.Label(splash, text="🤖  Personal AI", font=("Segoe UI", 22, "bold"),
         fg="#00d4ff", bg="#1a1a2e").pack(pady=(30, 5))
tk.Label(splash, text="Запуск системы...", font=("Segoe UI", 11),
         fg="#888888", bg="#1a1a2e").pack()

progress_var = tk.StringVar(value="Инициализация...")
tk.Label(splash, textvariable=progress_var, font=("Segoe UI", 10),
         fg="#aaaaaa", bg="#1a1a2e").pack(pady=5)

pb = ttk.Progressbar(splash, mode="indeterminate", length=300)
pb.pack(pady=10)
pb.start(15)

splash.update()

# ── Загрузка в фоновом потоке ─────────────────────────────────────────────────
_ready = threading.Event()
_error = [None]

def _load():
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE / ".env")

        splash.after(0, lambda: progress_var.set("Загрузка памяти и агентов..."))

        from main import main
        splash.after(0, lambda: progress_var.set("Открываю панель..."))
        splash.after(500, splash.destroy)   # закрываем splash через 0.5 сек
        main(no_gui=False, no_telegram=True)

    except Exception as e:
        import traceback
        _error[0] = traceback.format_exc()
        splash.after(0, _show_error)

def _show_error():
    pb.stop()
    splash.attributes("-topmost", True)
    splash.geometry("500x320")
    for w in splash.winfo_children():
        w.destroy()
    tk.Label(splash, text="⚠  Ошибка запуска", font=("Segoe UI", 16, "bold"),
             fg="#ff4444", bg="#1a1a2e").pack(pady=10)
    t = tk.Text(splash, height=12, bg="#0d0d1a", fg="#ff8888",
                font=("Consolas", 8), wrap=tk.WORD)
    t.insert("1.0", _error[0] or "Unknown error")
    t.pack(fill=tk.BOTH, expand=True, padx=10)
    tk.Button(splash, text="Закрыть", command=splash.destroy,
              bg="#333", fg="white").pack(pady=5)

threading.Thread(target=_load, daemon=True).start()
splash.mainloop()
