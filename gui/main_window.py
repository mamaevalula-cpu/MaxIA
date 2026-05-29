# -*- coding: utf-8 -*-
"""
gui/main_window.py — Personal AI GUI v3.0 (Production-Grade)

Исправления v3.0 (vs v2.x):
  ✅ Точный авторазмер пузырей чата — больше нет обрезанных сообщений
  ✅ Ctrl+X (вырезать) в поле ввода
  ✅ Вставка изображений из буфера (Ctrl+V с картинкой)
  ✅ Исправлен race condition с _thinking флагом
  ✅ Watchdog сбрасывается надёжно через threading.Event
  ✅ Панель выбора модели внизу чата (Auto / Claude / GPT / Gemini / Groq / DeepSeek)
  ✅ Счётчик токенов с иконкой ⚙
  ✅ Кнопка "+ Подпроект" в шапке
  ✅ Индикатор прогресса (шаги обработки)
  ✅ Полный UX стек — клавиши, контекстные меню, drag-and-drop изображений

Архитектура:
  PersonalAIGUI
    ├── _build()            — построить все вкладки
    ├── _tab_chat()         — чат с AI (главная вкладка)
    │     ├── _chat_add()       — добавить пузырь
    │     ├── _resize_bubble()  — точный авторазмер через displaylines
    │     ├── _send()           — отправить запрос
    │     └── _model_bar()      — панель выбора модели + токены
    ├── _tab_dashboard()    — дашборд системы
    ├── _tab_agents()       — агенты
    ├── _tab_projects()     — проекты + подпроекты
    ├── _tab_auth()         — авторизация / ключи
    └── _tab_settings()     — настройки

Потокобезопасно: queue.Queue + root.after(100)
"""

from __future__ import annotations

import base64
import io
import json
import os
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import customtkinter as ctk
    CTK = True
except ImportError:
    import tkinter as tk
    import tkinter.ttk as ttk
    CTK = False

try:
    from PIL import Image, ImageTk, ImageGrab
    PIL_OK = True
except ImportError:
    PIL_OK = False

from core.config import cfg
from core.logger import get_logger

log = get_logger("gui.main")

# ── Цвета ─────────────────────────────────────────────────────────────────────
C = {
    "bg":          "#F0F4F8",
    "card":        "#FFFFFF",
    "sidebar":     "#1A2332",
    "sidebar_sel": "#2563EB",
    "sidebar_txt": "#CBD5E1",
    "accent":      "#2563EB",
    "accent_h":    "#1D4ED8",
    "success":     "#16A34A",
    "warning":     "#D97706",
    "error":       "#DC2626",
    "txt":         "#1E293B",
    "txt2":        "#64748B",
    "border":      "#E2E8F0",
    "input_bg":    "#EEF2F7",
    "user_bg":     "#EFF6FF",
    "bot_bg":      "#F1F5F9",
    "model_bar":   "#F8FAFC",
    "token_ok":    "#DCFCE7",
    "token_warn":  "#FEF9C3",
    "token_crit":  "#FEE2E2",
}
FF = "Segoe UI" if sys.platform == "win32" else "SF Pro Text" if sys.platform == "darwin" else "Ubuntu"

# ── Доступные модели ─────────────────────────────────────────────────────────
MODELS = {
    "🤖 Auto":          "auto",
    "💎 Claude Opus":   "claude",
    "⚡ Claude Haiku":  "claude_haiku",
    "🟢 GPT-4o":        "openai",
    "✨ Gemini Flash":  "gemini",
    "🔵 DeepSeek R1":   "deepseek",
    "⚡ Groq (fast)":   "groq",
    "🔥 Grok":          "grok",
}

# ── Токен-лимиты по провайдерам (приблизительные) ────────────────────────────
TOKEN_LIMITS = {
    "auto":         200_000,
    "claude":       200_000,
    "claude_haiku": 200_000,
    "openai":       128_000,
    "gemini":     1_000_000,
    "deepseek":     64_000,
    "groq":         32_768,
    "grok":        131_072,
}


def _darken(hex_color: str) -> str:
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return "#{:02x}{:02x}{:02x}".format(int(r*.85), int(g*.85), int(b*.85))
    except Exception:
        return hex_color


def _card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=12,
                        border_width=1, border_color=C["border"], **kw)


def _label(parent, text, size=13, bold=False, color=None, **kw):
    return ctk.CTkLabel(
        parent, text=text,
        font=ctk.CTkFont(family=FF, size=size, weight="bold" if bold else "normal"),
        text_color=color or C["txt"], **kw
    )


def _btn(parent, text, cmd, color=None, width=120, height=34, **kw):
    c = color or C["accent"]
    return ctk.CTkButton(
        parent, text=text, command=cmd,
        fg_color=c, hover_color=_darken(c),
        font=ctk.CTkFont(family=FF, size=12),
        width=width, height=height,
        corner_radius=8, **kw
    )


# ══════════════════════════════════════════════════════════════════════════════
# ГЛАВНОЕ ОКНО
# ══════════════════════════════════════════════════════════════════════════════

class PersonalAIGUI:
    """Главное окно системы my_personal_ai v3.0."""

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._brain = None
        self._agents: Dict[str, Any] = {}
        self._current_tab = "chat"
        self._thinking = False
        self._thinking_lock = threading.Lock()
        self._watchdog_event = threading.Event()   # сигнал watchdog'у что ответ получен
        self._selected_model = "auto"
        self._tokens_used = 0
        self._session_tokens = 0
        self._browser_panel_mounted = False        # lazy init guard for BrowserPanel
        self._browser_panel_frame = None           # set in _tab_browser()
        self._task_panel_mounted = False           # lazy init guard for TaskPanel
        self._task_panel_frame = None              # set in _tab_task()

        if CTK:
            ctk.set_appearance_mode("light")
            ctk.set_default_color_theme("blue")
            self._root = ctk.CTk()
        else:
            import tkinter as tk
            self._root = tk.Tk()

        self._root.title("🧠 Personal AI  —  Автономный ИИ-Ассистент")

        # Центрируем окно на экране
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        w, h = min(1380, sw - 40), min(880, sh - 80)
        x = (sw - w) // 2
        y = (sh - h) // 2
        self._root.geometry(f"{w}x{h}+{x}+{y}")
        self._root.minsize(1100, 700)

        if CTK:
            self._root.configure(fg_color=C["bg"])
            self._build()
        else:
            self._build_tk()

        # Принудительно выводим окно на передний план
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()
        self._root.attributes("-topmost", True)
        self._root.after(800, lambda: self._root.attributes("-topmost", False))

        # Windows API: форсируем окно на передний план через ctypes
        if sys.platform == "win32":
            try:
                import ctypes
                self._root.update()  # убеждаемся что hwnd создан
                hwnd = self._root.winfo_id()
                ctypes.windll.user32.ShowWindow(hwnd, 9)        # SW_RESTORE
                ctypes.windll.user32.BringWindowToTop(hwnd)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

        self._start_queue()
        self._load_ui_state()
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ══════════════════════════════════════════════════════════════════════════
    # СОСТОЯНИЕ UI (persistence)
    # ══════════════════════════════════════════════════════════════════════════

    def _ui_state_path(self) -> Path:
        try:
            from core.config import cfg
            return cfg.BASE_DIR / "data" / "ui_state.json"
        except Exception:
            return Path(__file__).parent.parent / "data" / "ui_state.json"

    def _load_ui_state(self) -> None:
        try:
            p = self._ui_state_path()
            if p.exists():
                state = json.loads(p.read_text(encoding="utf-8"))
                tab = state.get("current_tab", "chat")
                model = state.get("selected_model", "auto")
                if tab in self._tabs:
                    self._switch(tab)
                if model in MODELS.values():
                    self._selected_model = model
                    if hasattr(self, "_model_var"):
                        for label, key in MODELS.items():
                            if key == model:
                                self._model_var.set(label)
                                break
        except Exception:
            pass

    def _save_ui_state(self) -> None:
        try:
            p = self._ui_state_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "current_tab":     self._current_tab,
                "selected_model":  self._selected_model,
                "saved_at":        datetime.now().isoformat(),
            }
            p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _on_close(self) -> None:
        self._save_ui_state()
        self._root.destroy()

    def _start_health_ping(self) -> None:
        """Фоновый поток: пингует brain каждые 30с, обновляет статус-бар."""
        def _ping():
            while True:
                time.sleep(30)
                try:
                    if self._brain is not None:
                        # Brain подключён — проверяем LLM
                        from brain.llm_router import LLMRouter
                        report = LLMRouter.get().status_report()
                        avail = sum(1 for v in report.values() if v.get("available"))
                        total = len(report)
                        if avail > 0:
                            self._q.put({"action": "update_status",
                                         "text": f"● Работает ({avail}/{total} LLM)"})
                            self._q.put({"action": "_update_daemon_lbl",
                                         "text": f"⬤ Brain OK  |  {avail} LLM", "color": "#16A34A"})
                        else:
                            self._q.put({"action": "update_status",
                                         "text": "⚠️ Нет LLM провайдеров"})
                            self._q.put({"action": "_update_daemon_lbl",
                                         "text": "⬤ Нет LLM", "color": "#D97706"})
                    else:
                        self._q.put({"action": "_update_daemon_lbl",
                                     "text": "⬤ Brain не подключён", "color": "#64748B"})
                except Exception:
                    pass

        # Check daemon PID
        try:
            from pathlib import Path as _P
            pid_f = _P(__file__).parent.parent / "data" / "daemon.pid"
            if pid_f.exists():
                pid = int(pid_f.read_text().strip())
                import os as _os
                try:
                    _os.kill(pid, 0)  # check if process alive
                    self._q.put({"action": "_update_daemon_lbl",
                                 "text": f"⬤ Daemon PID {pid}", "color": "#16A34A"})
                except OSError:
                    pid_f.unlink(missing_ok=True)
        except Exception:
            pass

        threading.Thread(target=_ping, daemon=True, name="gui-health-ping").start()

    # ══════════════════════════════════════════════════════════════════════════
    # ПОСТРОЕНИЕ UI
    # ══════════════════════════════════════════════════════════════════════════

    def _build(self) -> None:
        root = self._root
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(0, weight=1)

        # ── Сайдбар ───────────────────────────────────────────────────────────
        sb = ctk.CTkFrame(root, width=220, corner_radius=0, fg_color=C["sidebar"])
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(20, weight=1)

        ctk.CTkLabel(sb, text="🧠  Personal AI",
                     font=ctk.CTkFont(family=FF, size=17, weight="bold"),
                     text_color="#F8FAFC").grid(row=0, column=0, padx=20, pady=(22, 28), sticky="w")

        self._nav: Dict[str, ctk.CTkButton] = {}
        items = [
            ("💬  Чат",          "chat"),
            ("📈  Трейдинг",     "trading"),
            ("📊  Дашборд",      "dashboard"),
            ("🤖  Агенты",       "agents"),
            ("⚡  Задачи",       "task"),
            ("📁  Проекты",      "projects"),
            ("💼  Фриланс",      "freelance"),
            ("💳  Платежи",      "payment"),
            ("🌐  Браузер",      "browser"),
            ("🔐  Авторизация",  "auth"),
            ("⚙️  Настройки",    "settings"),
        ]
        for i, (label, key) in enumerate(items, 1):
            btn = ctk.CTkButton(
                sb, text=label, anchor="w",
                width=192, height=38, corner_radius=8,
                fg_color="transparent", hover_color="#2D3F55",
                text_color=C["sidebar_txt"],
                font=ctk.CTkFont(family=FF, size=13),
                command=lambda k=key: self._switch(k),
            )
            btn.grid(row=i, column=0, padx=14, pady=3, sticky="w")
            self._nav[key] = btn

        # Версия + статус + daemon indicator
        self._sb_status = ctk.CTkLabel(
            sb, text="● Инициализация...",
            font=ctk.CTkFont(family=FF, size=11), text_color="#64748B")
        self._sb_status.grid(row=21, column=0, padx=16, pady=(0, 2), sticky="sw")

        # 24/7 daemon status
        self._daemon_lbl = ctk.CTkLabel(
            sb, text="⬤ UI mode",
            font=ctk.CTkFont(family=FF, size=10), text_color="#334155")
        self._daemon_lbl.grid(row=22, column=0, padx=16, pady=(0, 2), sticky="sw")

        ctk.CTkLabel(sb, text="v3.1 Production",
                     font=ctk.CTkFont(family=FF, size=9), text_color="#2D3F55"
                     ).grid(row=23, column=0, padx=16, pady=(0, 10), sticky="sw")

        # Start background health pinger
        self._start_health_ping()

        # ── Контент ───────────────────────────────────────────────────────────
        self._content = ctk.CTkFrame(root, fg_color=C["bg"], corner_radius=0)
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        self._tabs: Dict[str, ctk.CTkFrame] = {
            "chat":      self._tab_chat(),
            "trading":   self._tab_trading(),
            "dashboard": self._tab_dashboard(),
            "agents":    self._tab_agents(),
            "task":      self._tab_task(),
            "projects":  self._tab_projects(),
            "freelance": self._tab_freelance(),
            "payment":   self._tab_payment(),
            "browser":   self._tab_browser(),
            "auth":      self._tab_auth(),
            "settings":  self._tab_settings(),
        }
        for tab in self._tabs.values():
            tab.grid(row=0, column=0, sticky="nsew")
            tab.grid_remove()

        self._switch("chat")

    # ══════════════════════════════════════════════════════════════════════════
    # ВКЛАДКА: ЧАТ (полностью переработана)
    # ══════════════════════════════════════════════════════════════════════════

    def _tab_chat(self) -> ctk.CTkFrame:
        import tkinter as tk
        f = ctk.CTkFrame(self._content, fg_color=C["bg"], corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)  # chat_box расширяется

        # ── Шапка ─────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(f, fg_color=C["card"], corner_radius=0, height=58)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)
        hdr.grid_propagate(False)

        _label(hdr, "💬  Чат с AI-Ассистентом", 16, bold=True).grid(
            row=0, column=0, padx=20, pady=14, sticky="w")

        # Правые кнопки шапки
        btns_right = ctk.CTkFrame(hdr, fg_color="transparent")
        btns_right.grid(row=0, column=1, padx=8, pady=14, sticky="e")
        _btn(btns_right, "🗑 Чат", self._clear_chat,
             color=C["error"], width=80, height=28).pack(side="right", padx=(4, 0))
        _btn(btns_right, "+ Подпроект", self._new_subproject_dlg,
             color="#7C3AED", width=118, height=28).pack(side="right", padx=4)

        self._provider_lbl = _label(hdr, "LLM: ожидание...", 11, color=C["txt2"])
        self._provider_lbl.grid(row=0, column=2, padx=20, sticky="e")

        # ── Область сообщений ─────────────────────────────────────────────────
        self._chat_box = ctk.CTkScrollableFrame(f, fg_color=C["bg"], corner_radius=0)
        self._chat_box.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self._chat_box.grid_columnconfigure(0, weight=1)
        self._chat_row = 0

        # ── Панель ввода ───────────────────────────────────────────────────────
        inp_outer = ctk.CTkFrame(f, fg_color=C["card"], corner_radius=0)
        inp_outer.grid(row=2, column=0, sticky="ew")
        inp_outer.grid_columnconfigure(0, weight=1)

        # Строка ввода
        inp = ctk.CTkFrame(inp_outer, fg_color="transparent")
        inp.grid(row=0, column=0, sticky="ew", padx=0, pady=(10, 0))
        inp.grid_columnconfigure(0, weight=1)

        inp_wrap = ctk.CTkFrame(inp, fg_color=C["input_bg"], corner_radius=12,
                                border_width=1, border_color=C["border"])
        inp_wrap.grid(row=0, column=0, padx=(14, 8), pady=0, sticky="ew")
        inp_wrap.grid_columnconfigure(0, weight=1)

        self._inp = tk.Text(
            inp_wrap,
            height=3,
            font=(FF, 13),
            fg=C["txt2"],
            bg=C["input_bg"],
            relief="flat", bd=0,
            wrap="word",
            cursor="xterm",
            highlightthickness=0,
            padx=10, pady=8,
            insertbackground=C["accent"],
            selectbackground="#93C5FD",
            selectforeground=C["txt"],
            undo=True, maxundo=50,
        )
        self._inp.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        self._inp.insert("1.0", "Напиши запрос... (Enter — отправить, Shift+Enter — новая строка)")
        self._ph = True

        # Привязки клавиш
        self._inp.bind("<FocusIn>",    self._inp_focus_in)
        self._inp.bind("<FocusOut>",   self._inp_focus_out)
        self._inp.bind("<Return>",     self._inp_enter)
        self._inp.bind("<Control-v>",  self._inp_paste)
        self._inp.bind("<Control-V>",  self._inp_paste)
        self._inp.bind("<Control-x>",  self._inp_cut)
        self._inp.bind("<Control-X>",  self._inp_cut)
        self._inp.bind("<Control-a>",  self._inp_select_all)
        self._inp.bind("<Control-A>",  self._inp_select_all)
        self._inp.bind("<Control-z>",  lambda e: self._inp.edit_undo() or "break")
        self._inp.bind("<Control-Z>",  lambda e: self._inp.edit_undo() or "break")
        self._inp.bind("<Control-y>",  lambda e: self._inp.edit_redo() or "break")
        self._inp.bind("<Button-3>",   self._inp_right_click)

        # Кнопка отправки
        send_btn = _btn(inp, "  ➤", self._send, width=54, height=62)
        send_btn.grid(row=0, column=1, padx=(0, 14), pady=0)
        self._send_btn = send_btn

        # ── Панель модели + токены ─────────────────────────────────────────────
        self._build_model_bar(inp_outer)

        return f

    def _build_model_bar(self, parent) -> None:
        """Нижняя панель: выбор модели + токен-счётчик."""
        import tkinter as tk
        bar = ctk.CTkFrame(parent, fg_color=C["model_bar"],
                           corner_radius=0, height=38,
                           border_width=1, border_color=C["border"])
        bar.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        bar.grid_columnconfigure(3, weight=1)
        bar.grid_propagate(False)

        # Метка "Модель:"
        _label(bar, "Модель:", 11, color=C["txt2"]).grid(
            row=0, column=0, padx=(14, 4), pady=8, sticky="w")

        # Выпадающий список моделей
        model_names = list(MODELS.keys())
        self._model_var = tk.StringVar(value=model_names[0])
        model_dd = ctk.CTkOptionMenu(
            bar,
            values=model_names,
            variable=self._model_var,
            command=self._on_model_change,
            font=ctk.CTkFont(family=FF, size=11),
            width=150, height=26,
            fg_color=C["input_bg"],
            button_color=C["accent"],
            button_hover_color=_darken(C["accent"]),
            text_color=C["txt"],
            dropdown_fg_color=C["card"],
            dropdown_text_color=C["txt"],
            corner_radius=6,
        )
        model_dd.grid(row=0, column=1, padx=(0, 12), pady=6, sticky="w")

        # Разделитель
        ctk.CTkFrame(bar, fg_color=C["border"], width=1, height=22).grid(
            row=0, column=2, padx=4, pady=8)

        # Токен-счётчик — кликабельный
        self._token_frame = ctk.CTkFrame(bar, fg_color=C["token_ok"],
                                          corner_radius=6, height=24)
        self._token_frame.grid(row=0, column=4, padx=(0, 14), pady=7, sticky="e")
        self._token_label = ctk.CTkLabel(
            self._token_frame,
            text="⚙  0 / 200K токенов",
            font=ctk.CTkFont(family=FF, size=10),
            text_color=C["txt2"],
        )
        self._token_label.pack(padx=8, pady=2)
        self._token_frame.bind("<Button-1>", self._show_token_details)
        self._token_label.bind("<Button-1>", self._show_token_details)

        # Статус "Экономный режим" / "Мощный режим"
        self._mode_lbl = _label(bar, "⚡ Авто", 10, color=C["txt2"])
        self._mode_lbl.grid(row=0, column=5, padx=(0, 8), pady=8, sticky="e")

    def _on_model_change(self, choice: str) -> None:
        self._selected_model = MODELS.get(choice, "auto")
        limit = TOKEN_LIMITS.get(self._selected_model, 200_000)

        mode_texts = {
            "auto":         "⚡ Авто",
            "claude_haiku": "💰 Эконом",
            "groq":         "💰 Быстро",
            "claude":       "💎 Мощный",
            "openai":       "💎 Мощный",
            "gemini":       "🔍 Поиск",
            "deepseek":     "🧠 Reasoning",
            "grok":         "🔥 Grok",
        }
        self._mode_lbl.configure(text=mode_texts.get(self._selected_model, "⚡ Авто"))
        self._update_token_display()
        log.debug("Model selected: %s → %s", choice, self._selected_model)

    def _update_token_display(self) -> None:
        """Обновить счётчик токенов."""
        limit = TOKEN_LIMITS.get(self._selected_model, 200_000)
        used = self._session_tokens
        pct = used / max(limit, 1)

        if pct < 0.6:
            color = C["token_ok"]
            icon = "⚙"
        elif pct < 0.85:
            color = C["token_warn"]
            icon = "⚠"
        else:
            color = C["token_crit"]
            icon = "🔴"

        limit_str = f"{limit // 1000}K" if limit < 1_000_000 else f"{limit // 1_000_000}M"
        used_str  = f"{used // 1000}K" if used >= 1000 else str(used)
        self._token_frame.configure(fg_color=color)
        self._token_label.configure(text=f"{icon}  {used_str} / {limit_str} токенов")

    def _show_token_details(self, event=None) -> None:
        """Показать детальную статистику токенов."""
        import tkinter as tk
        dlg = tk.Toplevel(self._root)
        dlg.title("Статистика токенов")
        dlg.geometry("400x320")
        dlg.configure(bg=C["bg"])
        dlg.grab_set()
        dlg.resizable(False, False)

        _label(dlg, "📊 Расход токенов по провайдерам", 14, bold=True).pack(
            padx=16, pady=(16, 8), anchor="w")

        # Получить реальную статистику
        stats_text = ""
        try:
            from brain.llm_router import LLMRouter
            report = LLMRouter.get().status_report()
            for prov, info in report.items():
                icon = "✅" if info.get("available") else "❌"
                stats_text += f"  {icon} {prov:15s}: {info.get('requests', 0)} запросов\n"
        except Exception:
            stats_text = "  Статистика недоступна"

        txt = tk.Text(dlg, height=10, font=(FF, 11), bg=C["input_bg"],
                      relief="flat", bd=0, padx=12, pady=8)
        txt.pack(fill="both", expand=True, padx=16, pady=4)
        txt.insert("1.0", f"Сессия: {self._session_tokens} токенов использовано\n\n"
                          f"Провайдеры:\n{stats_text}")
        txt.configure(state="disabled")

        _btn(dlg, "✕ Закрыть", dlg.destroy, width=100, height=30).pack(pady=8)

    # ── Ввод текста ──────────────────────────────────────────────────────────

    def _inp_focus_in(self, e):
        if self._ph:
            self._inp.delete("1.0", "end")
            self._inp.configure(fg=C["txt"])
            self._ph = False

    def _inp_focus_out(self, e):
        if not self._inp.get("1.0", "end").strip():
            self._inp.insert("1.0", "Напиши запрос... (Enter — отправить, Shift+Enter — новая строка)")
            self._inp.configure(fg=C["txt2"])
            self._ph = True

    def _inp_enter(self, e) -> str:
        if e.state & 0x1:  # Shift+Enter = новая строка
            return None
        self._send()
        return "break"

    def _inp_paste(self, e=None) -> str:
        """Ctrl+V — вставить текст или изображение из буфера."""
        if self._ph:
            self._inp.delete("1.0", "end")
            self._inp.configure(fg=C["txt"])
            self._ph = False

        # Пробуем вставить как изображение (PIL)
        if PIL_OK:
            try:
                img = ImageGrab.grabclipboard()
                if isinstance(img, Image.Image):
                    self._insert_image(img)
                    return "break"
            except Exception:
                pass

        # Обычная вставка текста
        try:
            text = self._root.clipboard_get()
            self._inp.insert("insert", text)
        except Exception:
            pass
        return "break"

    def _inp_cut(self, e=None) -> str:
        """Ctrl+X — вырезать выделенный текст."""
        if self._ph:
            return "break"
        try:
            sel = self._inp.get("sel.first", "sel.last")
            self._root.clipboard_clear()
            self._root.clipboard_append(sel)
            self._inp.delete("sel.first", "sel.last")
        except Exception:
            pass
        return "break"

    def _inp_select_all(self, e=None) -> str:
        if not self._ph:
            self._inp.tag_add("sel", "1.0", "end")
        return "break"

    def _inp_right_click(self, event) -> None:
        import tkinter as _tk
        ctx = _tk.Menu(self._root, tearoff=0, font=(FF, 11),
                       bg=C["card"], fg=C["txt"],
                       activebackground=C["accent"], activeforeground="white")
        ctx.add_command(label="  Вырезать      Ctrl+X  ", command=lambda: self._inp_cut())
        ctx.add_command(label="  Копировать    Ctrl+C  ",
                        command=lambda: (self._root.clipboard_clear(),
                                        self._root.clipboard_append(
                                            self._inp.get("sel.first", "sel.last"))))
        ctx.add_command(label="  Вставить      Ctrl+V  ", command=self._inp_paste)
        ctx.add_separator()
        ctx.add_command(label="  Выделить всё  Ctrl+A  ", command=self._inp_select_all)
        ctx.add_separator()
        ctx.add_command(label="  Очистить поле           ",
                        command=lambda: (self._inp.delete("1.0", "end"), self.__setattr__("_ph", False)))
        ctx.tk_popup(event.x_root, event.y_root)

    def _insert_image(self, img: "Image.Image") -> None:
        """Вставить изображение из буфера в чат (отправить на анализ)."""
        import tkinter as _tk
        # Масштабировать для превью
        preview = img.copy()
        preview.thumbnail((200, 150))
        photo = ImageTk.PhotoImage(preview)

        # Хранить ссылку чтобы GC не удалил
        if not hasattr(self, "_img_refs"):
            self._img_refs = []
        self._img_refs.append(photo)

        # Вставить в поле ввода как метку
        self._inp.image_create("insert", image=photo)
        self._inp.insert("insert", " [изображение] ")

        # Сохранить raw bytes для отправки
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        self._pending_image_bytes = buf.getvalue()
        log.debug("Image pasted: %dx%d", img.width, img.height)

    # ══════════════════════════════════════════════════════════════════════════
    # ОТПРАВКА И ОБРАБОТКА
    # ══════════════════════════════════════════════════════════════════════════

    def _send(self) -> None:
        if self._ph:
            return
        text = self._inp.get("1.0", "end").strip()
        # Убрать маркер изображения для проверки пустоты
        clean = text.replace("[изображение]", "").strip()
        if not clean or self._thinking:
            return

        # Очистить поле ввода
        self._inp.delete("1.0", "end")
        self._inp.configure(fg=C["txt"])
        self._ph = False

        # Заблокировать повторную отправку
        with self._thinking_lock:
            self._thinking = True
        self._send_btn.configure(state="disabled", fg_color=C["txt2"])

        # Забрать изображение если есть
        image_bytes = getattr(self, "_pending_image_bytes", None)
        self._pending_image_bytes = None

        self._chat_add("user", text)
        self._chat_add("bot", "⏳  Обрабатываю...", tag="thinking")

        def _on_step(msg: str) -> None:
            self._q.put({"action": "step_update", "text": msg})

        def _process():
            reply = "⏱️ Ответ не получен (попробуй ещё раз)."
            try:
                reply = self._call_brain(text, step_callback=_on_step,
                                         model=self._selected_model,
                                         image_bytes=image_bytes)
            except Exception as e:
                reply = f"❌ Критическая ошибка: {e}"
                log.error("_process exception: %s", e, exc_info=True)
            finally:
                self._watchdog_event.set()  # сигнализируем watchdog — ответ получен
                self._q.put({"action": "replace_thinking", "text": reply})
                # Сбрасываем флаг в основном потоке через очередь
                self._q.put({"action": "unblock"})

        threading.Thread(target=_process, daemon=True, name="brain-worker").start()

        # Watchdog: сбрасывает блокировку если ответ не пришёл через 120с
        def _watchdog():
            fired = not self._watchdog_event.wait(timeout=120)
            self._watchdog_event.clear()
            if fired:
                self._q.put({"action": "replace_thinking",
                             "text": "⏱️ Запрос занял слишком долго. Попробуй снова."})
                self._q.put({"action": "unblock"})
        threading.Thread(target=_watchdog, daemon=True, name="gui-watchdog").start()

    def _call_brain(self, text: str, step_callback=None,
                    model: str = "auto", image_bytes: bytes = None) -> str:
        """
        Вызвать мозг с учётом выбранной модели.
        Автоматически повторяет до 3 раз с экспоненциальным backoff при сбоях.
        """
        # Если есть изображение — добавить метаданные в запрос
        if image_bytes:
            encoded = base64.b64encode(image_bytes).decode()
            text = f"[IMAGE_DATA:base64:{len(encoded)}chars]\n{text}"

        _max_retries = 3
        _backoff = [0, 2, 5]   # секунды между попытками

        if self._brain is None:
            # Прямой вызов LLMRouter (без brain orchestrator)
            for attempt in range(_max_retries):
                try:
                    from brain.llm_router import LLMRouter, LLMRequest
                    router = LLMRouter.get()
                    if step_callback:
                        step_callback("🧠 Прямой вызов LLM..." +
                                      (f" (попытка {attempt+1})" if attempt else ""))
                    req = LLMRequest(
                        messages=[{"role": "user", "content": text}],
                        system="Ты персональный AI-ассистент. Отвечай на русском, ёмко и по делу.",
                        task_type="general", max_tokens=2000,
                        preferred_provider=model if model != "auto" else None,
                    )
                    resp = router.ask(req)
                    tokens = getattr(resp, "tokens_used", 0) or len(text.split()) * 1.3
                    self._q.put({"action": "add_tokens", "count": int(tokens)})
                    if resp.success:
                        return resp.content
                    # Провайдер вернул ошибку — retry только если не rate-limit
                    if "rate" in (resp.error or "").lower() and attempt < _max_retries - 1:
                        if step_callback:
                            step_callback(f"⏳ Rate limit — жду {_backoff[attempt+1]}с...")
                        time.sleep(_backoff[attempt + 1])
                        continue
                    return f"⚠️ LLM: {resp.error}"
                except Exception as e:
                    if attempt < _max_retries - 1:
                        if step_callback:
                            step_callback(f"⚠️ Ошибка (попытка {attempt+1}) — повтор...")
                        time.sleep(_backoff[attempt + 1])
                    else:
                        return f"⚠️ Brain не подключён: {e}"
            return "⚠️ Не удалось выполнить запрос (все попытки исчерпаны)."

        # Вызов через BrainOrchestrator
        for attempt in range(_max_retries):
            try:
                from brain.orchestrator import OrchestratorRequest
                if attempt and step_callback:
                    step_callback(f"🔄 Повтор запроса (попытка {attempt+1})...")
                req = OrchestratorRequest(
                    text=text, source="gui", session_id="gui",
                    progress_callback=step_callback,
                    metadata={"preferred_model": model},
                )
                resp = self._brain.process(req)
                tokens = len(text.split()) + len(resp.text.split())
                self._q.put({"action": "add_tokens", "count": tokens})
                # Обновить статус — провайдер успешно ответил
                provider_hint = getattr(resp, "provider", "")
                if provider_hint:
                    self._q.put({"action": "update_provider",
                                 "text": f"🟢 {provider_hint}"})
                return resp.text
            except Exception as e:
                err_str = str(e)
                is_transient = any(x in err_str.lower() for x in
                                   ("timeout", "connection", "rate", "503", "502"))
                if is_transient and attempt < _max_retries - 1:
                    delay = _backoff[attempt + 1]
                    if step_callback:
                        step_callback(f"⚠️ Сбой ({err_str[:40]}) — повтор через {delay}с...")
                    self._q.put({"action": "update_status",
                                 "text": f"⚠️ Ошибка (попытка {attempt+1}), повтор..."})
                    time.sleep(delay)
                else:
                    return f"❌ Ошибка: {e}"
        return "❌ Не удалось получить ответ (все попытки исчерпаны)."

    def _save_message(self, role: str, text: str) -> None:
        try:
            from memory.memory_store import MemoryStore, Message
            MemoryStore.get().add_message(Message(
                role=role, content=text, source="gui", session_id="gui",
            ))
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # ЧАТ: РЕНДЕР ПУЗЫРЕЙ (ПОЛНОСТЬЮ ПЕРЕРАБОТАН)
    # ══════════════════════════════════════════════════════════════════════════

    def _chat_add(self, role: str, text: str, tag: str = "") -> None:
        """
        Добавить пузырь сообщения в чат.

        ФИКС v3.0: Используем динамическое определение высоты через displaylines
        вместо приблизительного подсчёта символов. Это устраняет обрезание текста.
        """
        import tkinter as tk
        ts = datetime.now().strftime("%H:%M")

        if role == "user" and tag != "thinking":
            self._save_message("user", text)

        bubble_color = C["user_bg"] if role == "user" else C["bot_bg"]
        text_color   = C["txt"]
        copy_bg      = "#DBEAFE" if role == "user" else "#E2E8F0"
        prefix_text  = f"Ты  {ts}" if role == "user" else f"AI  {ts}"

        row = self._chat_row
        self._chat_row += 1

        bubble = ctk.CTkFrame(self._chat_box, fg_color=bubble_color,
                               corner_radius=10, border_width=1,
                               border_color=C["border"])
        bubble.grid(row=row, column=0, padx=10, pady=4, sticky="ew")
        bubble.grid_columnconfigure(0, weight=1)
        if tag:
            bubble._tag = tag  # type: ignore

        # ── Шапка пузыря ────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(bubble, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=10, pady=(6, 0), sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hdr, text=prefix_text,
                     font=ctk.CTkFont(family=FF, size=10, weight="bold"),
                     text_color=C["txt2"]).grid(row=0, column=0, sticky="w")

        copy_btn = ctk.CTkButton(
            hdr, text="⎘ Копировать", width=90, height=20,
            font=ctk.CTkFont(family=FF, size=10),
            fg_color=copy_bg, hover_color=C["border"],
            text_color=C["txt2"], corner_radius=6,
        )
        copy_btn.grid(row=0, column=1, padx=(0, 2), sticky="e")

        # ── Текстовый виджет ─────────────────────────────────────────────────
        # Начальная высота: 1 строка. Авторазмер произойдёт после рендера.
        txt_widget = tk.Text(
            bubble,
            height=1,                    # ← ФИКС: начинаем с 1, расширяем динамически
            font=(FF, 12),
            fg=text_color,
            bg=bubble_color,
            relief="flat", bd=0,
            wrap="word",
            cursor="xterm",
            selectbackground="#93C5FD",
            selectforeground=C["txt"],
            highlightthickness=0,
            padx=4, pady=2,
            state="normal",
        )
        txt_widget.insert("1.0", text)
        txt_widget.configure(state="disabled")
        txt_widget.grid(row=1, column=0, padx=12, pady=(2, 8), sticky="ew")

        # ── Авторазмер после рендера ─────────────────────────────────────────
        # after(10) — первая попытка, _resize_text_widget сам retry если нужно
        self._root.after(10, lambda w=txt_widget: self._resize_text_widget(w))

        # ── Копировать ───────────────────────────────────────────────────────
        def _copy_all(w=txt_widget):
            self._root.clipboard_clear()
            self._root.clipboard_append(w.get("1.0", "end-1c"))
            copy_btn.configure(text="✓ Скопировано!", fg_color="#BBF7D0")
            self._root.after(1500, lambda: copy_btn.configure(
                text="⎘ Копировать", fg_color=copy_bg))

        copy_btn.configure(command=_copy_all)

        def _show_ctx(event, w=txt_widget):
            import tkinter as _tk
            ctx = _tk.Menu(self._root, tearoff=0, font=(FF, 11),
                           bg=C["card"], fg=C["txt"],
                           activebackground=C["accent"], activeforeground="white")
            def _copy_sel():
                try:
                    sel = w.get("sel.first", "sel.last")
                    self._root.clipboard_clear()
                    self._root.clipboard_append(sel)
                except _tk.TclError:
                    _copy_all()
            ctx.add_command(label="  Копировать выделенное  ", command=_copy_sel)
            ctx.add_command(label="  Копировать всё         ", command=_copy_all)
            ctx.add_separator()
            ctx.add_command(label="  Выделить всё           ",
                            command=lambda: (w.configure(state="normal"),
                                            w.tag_add("sel", "1.0", "end"),
                                            w.configure(state="disabled")))
            ctx.tk_popup(event.x_root, event.y_root)

        txt_widget.bind("<Button-3>", _show_ctx)
        bubble.bind("<Button-3>", _show_ctx)

        def _ctrl_c(event, w=txt_widget):
            try:
                sel = w.get("sel.first", "sel.last")
                self._root.clipboard_clear()
                self._root.clipboard_append(sel)
            except Exception:
                self._root.clipboard_clear()
                self._root.clipboard_append(w.get("1.0", "end-1c"))
            return "break"

        def _ctrl_a(event, w=txt_widget):
            w.configure(state="normal")
            w.tag_add("sel", "1.0", "end")
            w.configure(state="disabled")
            return "break"

        txt_widget.bind("<Control-c>", _ctrl_c)
        txt_widget.bind("<Control-C>", _ctrl_c)
        txt_widget.bind("<Control-a>", _ctrl_a)
        txt_widget.bind("<Control-A>", _ctrl_a)
        txt_widget.bind("<Button-1>", lambda e, w=txt_widget: w.focus_set())

        if tag == "thinking":
            self._thinking_bubble = bubble
            self._thinking_widget = txt_widget

        self._root.after(80, self._scroll_bottom)

    def _resize_text_widget(self, widget, _retry: int = 0) -> None:
        """
        Точный авторазмер пузыря через displaylines.

        Требует чтобы виджет уже был отрисован (winfo_width > 10).
        Если виджет ещё не размещён — retry до 8 раз с нарастающей задержкой.
        """
        try:
            widget.update_idletasks()
            w = widget.winfo_width()
            if w <= 10:
                if _retry < 8:
                    delay = 80 * (2 ** min(_retry, 4))   # 80, 160, 320, 640, 1280 ms
                    self._root.after(delay,
                                     lambda: self._resize_text_widget(widget, _retry + 1))
                return

            widget.configure(state="normal")

            # Основной метод — displaylines (точный, учитывает word-wrap)
            try:
                result = widget.count("1.0", "end", "displaylines")
                h = max(1, result[0]) if (result and result[0] and result[0] > 0) else 0
            except Exception:
                h = 0

            # Запасной метод если displaylines дал 0 или ошибку
            if h == 0:
                content = widget.get("1.0", "end-1c")
                # Считаем явные переносы + оцениваем wrapping по ширине
                font_chars = max(1, (w - 24) // 8)  # ~8px на символ
                lines = 0
                for ln in content.split("\n"):
                    lines += max(1, -(-len(ln) // font_chars))  # ceiling division
                h = max(1, lines)

            widget.configure(height=h, state="disabled")
            self._root.after(30, self._scroll_bottom)
        except Exception:
            try:
                widget.configure(state="disabled")
            except Exception:
                pass

    def _scroll_bottom(self) -> None:
        """Прокрутить чат вниз — несколько методов для надёжности."""
        try:
            # Метод 1: внутренний канвас CustomTkinter
            canvas = self._chat_box._parent_canvas
            canvas.yview_moveto(1.0)
            return
        except Exception:
            pass
        try:
            # Метод 2: последний виджет в скроллируемом фрейме
            children = self._chat_box._scrollbar_frame.winfo_children() if hasattr(
                self._chat_box, "_scrollbar_frame") else []
            if children:
                children[-1].update_idletasks()
        except Exception:
            pass
        try:
            # Метод 3: прямой поиск канваса среди дочерних виджетов
            for child in self._chat_box.winfo_children():
                if "canvas" in str(type(child)).lower():
                    child.yview_moveto(1.0)
                    break
        except Exception:
            pass

    def _clear_chat(self) -> None:
        """Очистить все пузыри из чата."""
        import tkinter as _tk
        if not _tk.messagebox.askyesno("Очистить чат",
                                       "Очистить все сообщения из чата?\n(История в памяти сохранится)",
                                       parent=self._root):
            return
        for w in self._chat_box.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self._chat_row = 0
        if hasattr(self, "_thinking_bubble"):
            del self._thinking_bubble
        if hasattr(self, "_thinking_widget"):
            del self._thinking_widget

    def _update_step(self, step_text: str) -> None:
        """Обновить thinking-bubble текущим шагом (живое обновление)."""
        try:
            if hasattr(self, "_thinking_widget"):
                w = self._thinking_widget
                w.configure(state="normal")
                w.delete("1.0", "end")
                w.insert("1.0", step_text)
                w.configure(state="disabled", height=2)
        except Exception:
            pass

    def _replace_thinking(self, text: str) -> None:
        """Заменить 'Обрабатываю...' на реальный ответ."""
        try:
            if hasattr(self, "_thinking_widget"):
                w = self._thinking_widget
                w.configure(state="normal")
                w.delete("1.0", "end")
                w.insert("1.0", text)
                w.configure(state="disabled")
                if hasattr(self, "_thinking_bubble"):
                    self._thinking_bubble.configure(fg_color=C["bot_bg"])
                # Авторазмер для ответа
                self._root.after(60, lambda: self._resize_text_widget(w))
            else:
                self._chat_add("bot", text)
        except Exception:
            self._chat_add("bot", text)
        self._root.after(100, self._scroll_bottom)

    def _unblock_input(self) -> None:
        """Разблокировать поле ввода после ответа."""
        with self._thinking_lock:
            self._thinking = False
        self._send_btn.configure(state="normal", fg_color=C["accent"])
        # Обновить инфо о провайдере
        try:
            from brain.llm_router import LLMRouter
            report = LLMRouter.get().status_report()
            avail = [k for k, v in report.items() if v.get("available")]
            if avail:
                self._provider_lbl.configure(
                    text=f"LLM: {avail[0]}", text_color=C["success"])
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # ВКЛАДКА: ТРЕЙДИНГ
    # ══════════════════════════════════════════════════════════════════════════

    def _tab_trading(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=C["bg"], corner_radius=0)
        f.grid_columnconfigure((0, 1), weight=1)
        f.grid_rowconfigure(2, weight=1)

        # Шапка
        hdr = ctk.CTkFrame(f, fg_color=C["card"], corner_radius=0, height=58)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)
        hdr.grid_propagate(False)
        _label(hdr, "📈  Торговый Бот (Bybit)", 16, bold=True).grid(
            row=0, column=0, padx=20, pady=14, sticky="w")
        _btn(hdr, "🔄 Обновить", self._refresh_trading, width=100, height=28
             ).grid(row=0, column=2, padx=16, pady=14, sticky="e")

        # Статус-карточки
        self._trade_cards: Dict[str, ctk.CTkLabel] = {}
        cards_data = [
            ("💰 Баланс",     "balance",   "---"),
            ("📊 Позиций",    "positions", "0"),
            ("📈 PnL сегодня","daily_pnl", "---"),
            ("🔄 Статус",     "bot_status","---"),
        ]
        for i, (lbl, key, val) in enumerate(cards_data):
            card = _card(f)
            card.grid(row=1, column=i % 2, padx=8, pady=6, sticky="ew",
                      ipadx=10, ipady=4)
            _label(card, lbl, 11, color=C["txt2"]).pack(anchor="w", padx=14, pady=(10, 0))
            vl = _label(card, val, 22, bold=True, color=C["accent"])
            vl.pack(anchor="w", padx=14, pady=(2, 10))
            self._trade_cards[key] = vl

        # Лог действий бота
        log_card = _card(f)
        log_card.grid(row=2, column=0, columnspan=2, padx=8, pady=6, sticky="nsew")
        _label(log_card, "📋 Лог торгового бота", 13, bold=True).pack(
            anchor="w", padx=14, pady=(10, 4))

        import tkinter as tk
        self._trade_log = tk.Text(
            log_card, height=15, font=(FF, 11), bg=C["input_bg"],
            relief="flat", bd=0, padx=8, pady=6, wrap="word", state="disabled"
        )
        self._trade_log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Быстрые команды
        cmds_card = _card(f)
        cmds_card.grid(row=3, column=0, columnspan=2, padx=8, pady=6, sticky="ew")
        _label(cmds_card, "⚡ Быстрые команды", 12, bold=True).pack(
            anchor="w", padx=14, pady=(10, 6))
        cmds_row = ctk.CTkFrame(cmds_card, fg_color="transparent")
        cmds_row.pack(padx=14, pady=(0, 12), anchor="w")
        _btn(cmds_row, "📊 Статус",   lambda: self._trade_cmd("статус"),
             color=C["accent"], width=90, height=28).pack(side="left", padx=3)
        _btn(cmds_row, "💰 Баланс",   lambda: self._trade_cmd("баланс"),
             color=C["accent"], width=90, height=28).pack(side="left", padx=3)
        _btn(cmds_row, "📈 Позиции",  lambda: self._trade_cmd("позиции"),
             color=C["accent"], width=90, height=28).pack(side="left", padx=3)
        _btn(cmds_row, "⏸ Пауза",    lambda: self._trade_cmd("пауза"),
             color=C["warning"], width=80, height=28).pack(side="left", padx=3)
        _btn(cmds_row, "🛑 Стоп",     lambda: self._trade_cmd("стоп бот"),
             color=C["error"], width=80, height=28).pack(side="left", padx=3)

        return f

    def _trade_cmd(self, cmd: str) -> None:
        agent = self._agents.get("trading")
        if not agent:
            self._trade_log_append("⚠️ TradingAgent не подключён\n")
            return
        def _run():
            try:
                result = agent.process(cmd)
                self._q.put({"action": "trade_log", "text": f"→ {cmd}\n{result}\n\n"})
            except Exception as e:
                self._q.put({"action": "trade_log", "text": f"❌ {e}\n"})
        threading.Thread(target=_run, daemon=True).start()

    def _refresh_trading(self) -> None:
        def _run():
            try:
                from core.trading_bridge import TradingBridge
                bridge = TradingBridge.get()
                bot = bridge.get_status(force=True)
                # Map BotStatus → card dict
                pnl_str = f"{bot.daily_pnl:+.2f} USDT ({bot.daily_pnl_pct:+.2f}%)" \
                          if bot.online else "---"
                balance_str = f"{bot.balance_usdt:.2f} USDT" if bot.online else "---"
                positions_str = str(bot.open_positions) if bot.online else "---"
                status_str = bot.mode_label if bot.online else f"{bot.status_emoji} Offline"
                data = {
                    "balance":   balance_str,
                    "positions": positions_str,
                    "daily_pnl": pnl_str,
                    "bot_status": status_str,
                }
                self._q.put({"action": "update_trade_cards", "data": data})
                # Also log recent trades
                if bot.recent_trades:
                    lines = [f"\n{'─'*38}", "🔄 Свежие сделки (обновление):"]
                    for t in bot.recent_trades[:5]:
                        side_e = "🟢" if t.side.lower() == "buy" else "🔴"
                        lat = f" {t.latency_ms:.0f}ms" if t.latency_ms else ""
                        lines.append(f"  {side_e} {t.symbol} {t.side} "
                                     f"qty={t.qty} [{t.status}]{lat} @{t.submitted_dt}")
                    lines.append("")
                    self._q.put({"action": "trade_log",
                                 "text": "\n".join(lines) + "\n"})
                elif not bot.online:
                    self._q.put({"action": "trade_log",
                                 "text": "⚠️ Бот оффлайн или файл статуса не найден\n"})
            except Exception as e:
                self._q.put({"action": "trade_log", "text": f"⚠️ Bridge error: {e}\n"})
        threading.Thread(target=_run, daemon=True).start()

    def _trade_log_append(self, text: str) -> None:
        try:
            self._trade_log.configure(state="normal")
            self._trade_log.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
            self._trade_log.see("end")
            self._trade_log.configure(state="disabled")
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # ВКЛАДКА: ДАШБОРД
    # ══════════════════════════════════════════════════════════════════════════

    def _tab_dashboard(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=C["bg"], corner_radius=0)
        f.grid_columnconfigure((0, 1), weight=1)

        _label(f, "📊  Дашборд", 18, bold=True).grid(
            row=0, column=0, columnspan=2, padx=24, pady=(20, 12), sticky="w")

        self._dsh: Dict[str, ctk.CTkLabel] = {}
        counters = [
            ("🤖 Агентов активных",  "agents",    "0",  C["accent"]),
            ("💾 Знаний в памяти",   "knowledge", "0",  C["accent"]),
            ("📁 Проектов",          "projects",  "0",  C["accent"]),
            ("📋 Задач в очереди",   "tasks",     "0",  C["accent"]),
            ("💼 Предложений послано","proposals", "0",  C["success"]),
            ("💰 Заработано (USD)",  "earnings",  "$0", C["success"]),
        ]
        for i, (lbl, key, val, col) in enumerate(counters):
            card = _card(f)
            card.grid(row=1+(i//2), column=i%2, padx=10, pady=6,
                      sticky="ew", ipadx=10, ipady=6)
            _label(card, lbl, 11, color=C["txt2"]).pack(anchor="w", padx=14, pady=(10, 0))
            vl = _label(card, val, 26, bold=True, color=col)
            vl.pack(anchor="w", padx=14, pady=(2, 10))
            self._dsh[key] = vl

        # Evolution компоненты
        evo_card = _card(f)
        evo_card.grid(row=3, column=0, columnspan=2, padx=10, pady=6, sticky="ew")
        _label(evo_card, "🚀  Evolution Components", 14, bold=True).pack(
            anchor="w", padx=14, pady=(12, 2))
        self._evo_lbl = _label(evo_card, "Загрузка...", 11, color=C["txt2"])
        self._evo_lbl.pack(anchor="w", padx=14, pady=(0, 12))

        # LLM статус
        llm_card = _card(f)
        llm_card.grid(row=4, column=0, columnspan=2, padx=10, pady=6, sticky="ew")
        _label(llm_card, "🧠  LLM Провайдеры", 14, bold=True).pack(
            anchor="w", padx=14, pady=(12, 2))
        self._llm_lbl = _label(llm_card, "Проверка...", 12, color=C["txt2"])
        self._llm_lbl.pack(anchor="w", padx=14, pady=(0, 12))

        _btn(f, "🔄 Обновить", self._refresh_dashboard, width=120).grid(
            row=5, column=0, padx=10, pady=8, sticky="w")

        return f

    # ── АГЕНТЫ, ПРОЕКТЫ, AUTH, НАСТРОЙКИ (без изменений логики, улучшен UI) ──

    def _tab_agents(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=C["bg"], corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)
        _label(f, "🤖  Агенты", 18, bold=True).grid(
            row=0, column=0, padx=24, pady=(20, 8), sticky="w")
        self._agents_scroll = ctk.CTkScrollableFrame(f, fg_color=C["bg"], corner_radius=0)
        self._agents_scroll.grid(row=1, column=0, sticky="nsew", padx=14, pady=4)
        self._agents_scroll.grid_columnconfigure(0, weight=1)
        return f

    # ══════════════════════════════════════════════════════════════════════════
    # ВКЛАДКА: ЗАДАЧИ (AgentHarness ReAct loop)
    # ══════════════════════════════════════════════════════════════════════════

    def _tab_task(self) -> ctk.CTkFrame:
        """Вкладка автономного выполнения задач через ReAct агента."""
        f = ctk.CTkFrame(self._content, fg_color=C["bg"], corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(f, fg_color=C["card"], corner_radius=0, height=58)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)
        hdr.grid_propagate(False)
        _label(hdr, "⚡  Агент-исполнитель (ReAct)", 16, bold=True).grid(
            row=0, column=0, padx=20, pady=14, sticky="w")

        panel_host = ctk.CTkFrame(f, fg_color="#1e1e2e", corner_radius=0)
        panel_host.grid(row=1, column=0, sticky="nsew")
        self._task_panel_frame = panel_host
        return f

    def _mount_task_panel(self) -> None:
        """Lazy-init TaskPanel on first tab switch."""
        if self._task_panel_mounted:
            return
        self._task_panel_mounted = True
        try:
            from gui.task_panel import TaskPanel
            loop = getattr(self, "_async_loop", None)
            if loop is None:
                import asyncio
                loop = asyncio.new_event_loop()

                def _run_loop(lp):
                    lp.run_forever()

                import threading
                t = threading.Thread(target=_run_loop, args=(loop,), daemon=True)
                t.start()
                self._async_loop = loop

            TaskPanel(self._task_panel_frame, loop)
        except Exception as e:
            self._task_panel_error(str(e))

    def _task_panel_error(self, msg: str) -> None:
        if self._task_panel_frame:
            _label(self._task_panel_frame,
                   f"⚠️ Ошибка загрузки панели задач:\n{msg}",
                   13, color="#e74c3c").pack(padx=20, pady=20)

    def _tab_projects(self) -> ctk.CTkFrame:
        import tkinter as tk
        f = ctk.CTkFrame(self._content, fg_color=C["bg"], corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        # ── Шапка ─────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(f, fg_color=C["card"], corner_radius=0, height=58)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)
        hdr.grid_propagate(False)
        _label(hdr, "📁  Проекты", 16, bold=True).grid(
            row=0, column=0, padx=20, pady=14, sticky="w")
        btn_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_frame.grid(row=0, column=2, padx=8, pady=10, sticky="e")
        _btn(btn_frame, "🔄", self._render_projects,
             color=C["txt2"], width=36, height=34).pack(side="right", padx=2)
        _btn(btn_frame, "+ Подпроект", self._new_subproject_dlg,
             color="#7C3AED", width=118, height=34).pack(side="right", padx=2)
        _btn(btn_frame, "+ Проект", self._create_project_dlg,
             width=110, height=34).pack(side="right", padx=2)

        # ── Поиск ──────────────────────────────────────────────────────────────
        search_frame = ctk.CTkFrame(f, fg_color="transparent")
        search_frame.grid(row=1, column=0, sticky="ew", padx=14, pady=(8, 2))
        search_frame.grid_columnconfigure(0, weight=1)

        self._proj_search = ctk.CTkEntry(
            search_frame,
            placeholder_text="🔍  Поиск по проектам...",
            font=ctk.CTkFont(family=FF, size=12),
            height=34, corner_radius=8,
        )
        self._proj_search.grid(row=0, column=0, sticky="ew")
        self._proj_search.bind("<KeyRelease>", lambda e: self._render_projects())

        # ── Список проектов ────────────────────────────────────────────────────
        self._proj_scroll = ctk.CTkScrollableFrame(f, fg_color=C["bg"], corner_radius=0)
        self._proj_scroll.grid(row=2, column=0, sticky="nsew", padx=14, pady=4)
        self._proj_scroll.grid_columnconfigure(0, weight=1)
        return f

    # ══════════════════════════════════════════════════════════════════════════
    # ВКЛАДКА: БРАУЗЕР-АГЕНТ
    # ══════════════════════════════════════════════════════════════════════════

    def _tab_browser(self) -> ctk.CTkFrame:
        """Вкладка управления браузер-агентом (Playwright)."""
        import tkinter as tk
        f = ctk.CTkFrame(self._content, fg_color=C["bg"], corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)

        # Шапка
        hdr = ctk.CTkFrame(f, fg_color=C["card"], corner_radius=0, height=58)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)
        hdr.grid_propagate(False)
        _label(hdr, "🌐  Браузер-агент (Playwright)", 16, bold=True).grid(
            row=0, column=0, padx=20, pady=14, sticky="w")

        install_btn = _btn(hdr, "📦 Установить", self._browser_install,
                           color="#7C3AED", width=120, height=28)
        install_btn.grid(row=0, column=2, padx=16, pady=14, sticky="e")

        # Контейнер для BrowserPanel (Tkinter Frame)
        panel_host = ctk.CTkFrame(f, fg_color="#1e1e2e", corner_radius=0)
        panel_host.grid(row=1, column=0, sticky="nsew")
        panel_host.grid_columnconfigure(0, weight=1)
        panel_host.grid_rowconfigure(0, weight=1)

        # Ленивая инициализация — BrowserPanel монтируется при первом открытии вкладки
        self._browser_panel_frame = panel_host
        self._browser_panel_mounted = False

        return f

    def _mount_browser_panel(self) -> None:
        """Лениво создать BrowserPanel при первом переходе на вкладку."""
        if self._browser_panel_mounted or self._browser_panel_frame is None:
            return
        self._browser_panel_mounted = True
        try:
            import tkinter as tk
            from browser_agent.gui_panel import BrowserPanel
            host = self._browser_panel_frame
            # BrowserPanel ожидает обычный tk/ctk Frame как parent
            inner = tk.Frame(host, bg="#1e1e2e")
            inner.grid(row=0, column=0, sticky="nsew")
            host.grid_columnconfigure(0, weight=1)
            host.grid_rowconfigure(0, weight=1)
            BrowserPanel(inner)
            log.debug("BrowserPanel mounted")
        except ImportError as e:
            self._browser_panel_error(f"browser_agent не найден: {e}\n"
                                      "Убедись что модуль browser_agent/ существует.")
        except Exception as e:
            self._browser_panel_error(f"Ошибка загрузки BrowserPanel: {e}")

    def _browser_panel_error(self, msg: str) -> None:
        """Показать ошибку монтирования внутри вкладки браузера."""
        try:
            import tkinter as tk
            host = self._browser_panel_frame
            tk.Label(host, text=msg, bg="#1e1e2e", fg="#f38ba8",
                     font=("Consolas", 11), justify="left",
                     wraplength=700).grid(padx=20, pady=40)
        except Exception:
            pass

    def _browser_install(self) -> None:
        """Показать инструкцию по установке Playwright."""
        import tkinter as _tk
        dlg = _tk.Toplevel(self._root)
        dlg.title("Установка Playwright")
        dlg.geometry("520x280")
        dlg.configure(bg=C["bg"])
        dlg.grab_set()
        _label(dlg, "📦 Установка Playwright", 15, bold=True).pack(
            padx=16, pady=(16, 8), anchor="w")
        _label(dlg, "Выполни в терминале:", 12, color=C["txt2"]).pack(
            padx=16, pady=(0, 4), anchor="w")
        import tkinter as tk
        code = tk.Text(dlg, height=3, font=("Consolas", 12), bg=C["input_bg"],
                       relief="flat", bd=0, padx=12, pady=8)
        code.insert("1.0", "pip install playwright\nplaywright install chromium")
        code.configure(state="disabled")
        code.pack(fill="x", padx=16, pady=4)
        _label(dlg, "После установки перезапусти приложение.", 11,
               color=C["txt2"]).pack(padx=16, pady=8, anchor="w")
        _btn(dlg, "✕ Закрыть", dlg.destroy, width=100, height=30).pack(pady=8)

    # ══════════════════════════════════════════════════════════════════════════
    # ВКЛАДКА: ФРИЛАНС
    # ══════════════════════════════════════════════════════════════════════════

    def _tab_freelance(self) -> ctk.CTkFrame:
        import tkinter as tk
        f = ctk.CTkFrame(self._content, fg_color=C["bg"], corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        # ── Шапка ─────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(f, fg_color=C["card"], corner_radius=0, height=62)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)
        hdr.grid_propagate(False)
        _label(hdr, "💼  Фриланс & Автозаработок", 17, bold=True).grid(
            row=0, column=0, padx=20, pady=16, sticky="w")
        btn_row = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_row.grid(row=0, column=2, padx=12, pady=10, sticky="e")
        _btn(btn_row, "🔍 Найти вакансии",  self._fl_search,   color=C["accent"],  width=145, height=32).pack(side="left", padx=4)
        _btn(btn_row, "💡 Оценить проект",  self._fl_estimate, color=C["warning"], width=138, height=32).pack(side="left", padx=4)
        _btn(btn_row, "📊 Статистика",      self._fl_stats,    color=C["success"], width=120, height=32).pack(side="left", padx=4)

        # ── Быстрый поиск ─────────────────────────────────────────────────────
        srch_row = ctk.CTkFrame(f, fg_color=C["card"], corner_radius=8,
                                border_width=1, border_color=C["border"])
        srch_row.grid(row=1, column=0, padx=14, pady=(8, 4), sticky="ew")
        srch_row.grid_columnconfigure(1, weight=1)
        _label(srch_row, "🔎", 14).grid(row=0, column=0, padx=(14, 4), pady=8)
        self._fl_search_var = tk.StringVar()
        fl_ent = ctk.CTkEntry(
            srch_row, textvariable=self._fl_search_var,
            placeholder_text="Навыки / ключевые слова (python, stripe, fastapi...)",
            font=ctk.CTkFont(family=FF, size=12), height=30,
            fg_color=C["input_bg"], border_width=0, corner_radius=6,
        )
        fl_ent.grid(row=0, column=1, padx=8, pady=8, sticky="ew")
        fl_ent.bind("<Return>", lambda e: self._fl_search())

        # ── Список вакансий (прокручиваемый) ──────────────────────────────────
        self._fl_scroll = ctk.CTkScrollableFrame(f, fg_color=C["bg"], corner_radius=0)
        self._fl_scroll.grid(row=2, column=0, sticky="nsew", padx=14, pady=4)
        self._fl_scroll.grid_columnconfigure(0, weight=1)
        self._fl_jobs_list: List[dict] = []
        # Заглушка до первого обновления
        _label(self._fl_scroll, "Нажмите «🔍 Найти вакансии» для поиска.", 12,
               color=C["txt2"]).grid(padx=20, pady=40)
        return f

    def _refresh_freelance(self) -> None:
        """Обновить счётчики при переходе на вкладку."""
        pass  # lazy — пользователь сам жмёт кнопку поиска

    def _fl_search(self) -> None:
        """Запустить поиск вакансий через FreelanceAgent."""
        kw = getattr(self, "_fl_search_var", None)
        query = kw.get().strip() if kw else ""
        skills = [s.strip() for s in query.replace(",", " ").split() if s.strip()] or None
        self._q.put({"action": "update_status", "text": "🔍 Ищу вакансии..."})
        for w in self._fl_scroll.winfo_children():
            w.destroy()
        _label(self._fl_scroll, "⏳ Поиск вакансий...", 13, color=C["txt2"]).grid(padx=20, pady=40)

        def _run():
            try:
                from agents.freelance_agent import FreelanceAgent
                jobs = FreelanceAgent.get().search_jobs(
                    skills=skills, budget_min=50)
                self._q.put({"action": "_fl_render_jobs", "jobs": jobs})
            except Exception as e:
                self._q.put({"action": "_fl_render_jobs", "jobs": [], "error": str(e)})
        threading.Thread(target=_run, daemon=True).start()

    def _fl_estimate(self) -> None:
        """Диалог оценки проекта."""
        import tkinter as _tk
        dlg = _tk.Toplevel(self._root)
        dlg.title("💡 Оценить проект")
        dlg.geometry("520x360")
        dlg.configure(bg=C["bg"])
        dlg.grab_set()
        _label(dlg, "Опишите проект:", 12).pack(padx=16, pady=(16, 4), anchor="w")
        import tkinter as tk
        desc_box = tk.Text(dlg, height=7, font=(FF, 12), bg=C["input_bg"],
                           relief="flat", bd=4, padx=8, pady=6, wrap="word")
        desc_box.pack(fill="x", padx=16, pady=4)
        result_lbl = _label(dlg, "", 11, color=C["txt2"])
        result_lbl.pack(padx=16, pady=8, anchor="w")

        def _do_estimate():
            desc = desc_box.get("1.0", "end").strip()
            if not desc:
                return
            result_lbl.configure(text="⏳ Оцениваю...", text_color=C["txt2"])
            def _run():
                try:
                    from agents.freelance_agent import FreelanceAgent
                    est = FreelanceAgent.get().estimate_project(desc)
                    text = (f"⏱  Срок: {est.hours_min}–{est.hours_max} ч\n"
                            f"💰 Стоимость: ${est.price_min:,.0f}–${est.price_max:,.0f}\n"
                            f"🔧 Технологии: {', '.join(est.technologies[:6])}\n"
                            f"📈 Сложность: {est.complexity}")
                    self._q.put({"action": "_fl_estimate_result",
                                 "lbl": result_lbl, "text": text})
                except Exception as ex:
                    self._q.put({"action": "_fl_estimate_result",
                                 "lbl": result_lbl, "text": f"Ошибка: {ex}"})
            threading.Thread(target=_run, daemon=True).start()

        _btn(dlg, "⚡ Оценить", _do_estimate, color=C["accent"], width=110).pack(pady=4)

    def _fl_stats(self) -> None:
        """Показать диалог статистики заработка."""
        import tkinter as _tk
        dlg = _tk.Toplevel(self._root)
        dlg.title("📊 Статистика заработка")
        dlg.geometry("420x320")
        dlg.configure(bg=C["bg"])
        dlg.grab_set()
        _label(dlg, "📊 Статистика фриланса", 15, bold=True).pack(padx=16, pady=(16,8), anchor="w")
        info_lbl = _label(dlg, "Загрузка...", 12, color=C["txt2"])
        info_lbl.pack(padx=16, pady=4, anchor="w")
        def _load():
            try:
                from agents.freelance_agent import FreelanceAgent
                agent = FreelanceAgent.get()
                s = agent.track_earnings()
                total_usd = s.get("total_usd", 0)
                by_platform = s.get("by_platform", {})
                monthly = s.get("monthly", {})
                proposals = agent._db.get_proposals() if hasattr(agent._db, "get_proposals") else []
                won  = sum(1 for p in proposals if getattr(p,"status","") == "won")
                rej  = sum(1 for p in proposals if getattr(p,"status","") == "rejected")
                plat_str = ", ".join(f"{k}:${v:,.0f}" for k,v in by_platform.items()) or "—"
                lines = [
                    f"💰 Всего заработано:   ${total_usd:,.2f}",
                    f"📋 Предложений:        {len(proposals)}",
                    f"✅ Выиграно:           {won}",
                    f"❌ Отклонено:          {rej}",
                    f"🌐 По платформам:      {plat_str}",
                ]
                self._q.put({"action": "_fl_stats_result",
                             "lbl": info_lbl, "text": "\n".join(lines)})
            except Exception as ex:
                self._q.put({"action": "_fl_stats_result",
                             "lbl": info_lbl, "text": f"Ошибка: {ex}"})
        threading.Thread(target=_load, daemon=True).start()
        _btn(dlg, "✕ Закрыть", dlg.destroy, width=100, height=30).pack(pady=12)

    def _render_fl_jobs(self, jobs: List[dict], error: str = "") -> None:
        """Отрисовать список вакансий в прокручиваемом фрейме."""
        for w in self._fl_scroll.winfo_children():
            w.destroy()
        if error:
            _label(self._fl_scroll, f"⚠️ {error}", 12, color=C["error"]).grid(padx=20, pady=20)
            return
        if not jobs:
            _label(self._fl_scroll, "Вакансий не найдено. Попробуйте другие ключевые слова.", 12,
                   color=C["txt2"]).grid(padx=20, pady=40)
            return
        for i, job in enumerate(jobs):
            card = _card(self._fl_scroll)
            card.grid(row=i, column=0, padx=6, pady=5, sticky="ew")
            card.grid_columnconfigure(1, weight=1)
            score = job.get("match_score", 0) if isinstance(job, dict) else getattr(job, "match_score", 0)
            sc_col = C["success"] if score >= 0.7 else C["warning"] if score >= 0.4 else C["txt2"]
            title = job.get("title","") if isinstance(job, dict) else getattr(job, "title","")
            platform = job.get("platform","") if isinstance(job, dict) else getattr(job, "platform","")
            bmin = job.get("budget_min",0) if isinstance(job, dict) else getattr(job,"budget_min",0)
            bmax = job.get("budget_max",0) if isinstance(job, dict) else getattr(job,"budget_max",0)
            desc = job.get("description","") if isinstance(job, dict) else getattr(job,"description","")
            url  = job.get("url","") if isinstance(job, dict) else getattr(job,"url","")
            _label(card, f"[{int(score*100)}%] {title}", 13, bold=True,
                   color=sc_col).grid(row=0, column=0, columnspan=2, padx=14, pady=(10,0), sticky="w")
            _label(card, f"{platform}  ·  ${bmin:,.0f}–${bmax:,.0f}", 11,
                   color=C["txt2"]).grid(row=1, column=0, padx=14, pady=(2,0), sticky="w")
            _label(card, (desc[:120] + "…") if len(desc) > 120 else desc, 11,
                   color=C["txt2"]).grid(row=2, column=0, padx=14, pady=(2,8), sticky="w")
            btn_f = ctk.CTkFrame(card, fg_color="transparent")
            btn_f.grid(row=0, column=1, rowspan=3, padx=10, pady=8, sticky="e")
            job_ref = job
            _btn(btn_f, "✉️ Предложение", lambda j=job_ref: self._fl_generate_proposal(j),
                 color=C["accent"], width=130, height=28).pack(pady=2)
            if url:
                _btn(btn_f, "🔗 Открыть", lambda u=url: self._open_url(u),
                     color=C["txt2"], width=90, height=28).pack(pady=2)
        self._q.put({"action": "update_status", "text": f"● Найдено {len(jobs)} вакансий"})

    def _fl_generate_proposal(self, job) -> None:
        """Сгенерировать предложение для вакансии через AI."""
        self._q.put({"action": "update_status", "text": "✉️ Генерирую предложение..."})
        def _run():
            try:
                from agents.freelance_agent import FreelanceAgent
                agent = FreelanceAgent.get()
                if isinstance(job, dict):
                    from agents.freelance_agent import FreelanceJob
                    job_obj = FreelanceJob(
                        id=job.get("id",""), platform=job.get("platform",""),
                        title=job.get("title",""), description=job.get("description",""),
                        budget_min=float(job.get("budget_min",0)),
                        budget_max=float(job.get("budget_max",0)),
                        budget_type=job.get("budget_type","fixed"),
                        skills=job.get("skills",[]), match_score=job.get("match_score",0.0),
                        url=job.get("url",""),
                    )
                else:
                    job_obj = job
                proposal = agent.generate_proposal(job_obj)
                text = proposal.text if hasattr(proposal, "text") else str(proposal)
                self._q.put({"action": "_fl_show_proposal", "text": text,
                             "job_title": job_obj.title})
            except Exception as ex:
                self._q.put({"action": "update_status", "text": f"⚠️ Ошибка: {ex}"})
        threading.Thread(target=_run, daemon=True).start()

    def _show_fl_proposal(self, text: str, job_title: str) -> None:
        """Показать текст предложения в диалоге."""
        import tkinter as _tk, tkinter.scrolledtext as _st
        dlg = _tk.Toplevel(self._root)
        dlg.title(f"✉️ Предложение — {job_title[:40]}")
        dlg.geometry("680x520")
        dlg.configure(bg=C["bg"])
        _label(dlg, f"✉️ Предложение для: {job_title[:60]}", 13, bold=True).pack(
            padx=16, pady=(14, 6), anchor="w")
        st = _st.ScrolledText(dlg, font=(FF, 12), bg=C["input_bg"], relief="flat",
                              bd=4, padx=8, pady=6, wrap="word")
        st.pack(fill="both", expand=True, padx=16, pady=4)
        st.insert("1.0", text)
        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(pady=10)
        def _copy():
            dlg.clipboard_clear()
            dlg.clipboard_append(text)
            self._q.put({"action": "update_status", "text": "✅ Скопировано!"})
        _btn(btn_row, "📋 Копировать", _copy,  color=C["success"], width=110, height=30).pack(side="left", padx=6)
        _btn(btn_row, "✕ Закрыть",     dlg.destroy, color=C["txt2"],    width=90,  height=30).pack(side="left", padx=6)

    def _open_url(self, url: str) -> None:
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # ВКЛАДКА: ПЛАТЕЖИ
    # ══════════════════════════════════════════════════════════════════════════

    def _tab_payment(self) -> ctk.CTkFrame:
        import tkinter as tk
        f = ctk.CTkFrame(self._content, fg_color=C["bg"], corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        # ── Шапка ─────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(f, fg_color=C["card"], corner_radius=0, height=62)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)
        hdr.grid_propagate(False)
        _label(hdr, "💳  Платёжные системы", 17, bold=True).grid(
            row=0, column=0, padx=20, pady=16, sticky="w")
        btn_row = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_row.grid(row=0, column=2, padx=12, pady=10, sticky="e")
        _btn(btn_row, "⚡ Генератор кода",  self._pay_codegen,  color=C["accent"],  width=145, height=32).pack(side="left", padx=4)
        _btn(btn_row, "📄 Счёт (Invoice)",  self._pay_invoice,  color=C["success"], width=138, height=32).pack(side="left", padx=4)
        _btn(btn_row, "📊 Вебхуки",         self._pay_webhooks, color=C["warning"], width=110, height=32).pack(side="left", padx=4)

        # ── Быстрый выбор провайдера ───────────────────────────────────────────
        prov_row = ctk.CTkFrame(f, fg_color=C["card"], corner_radius=8,
                                border_width=1, border_color=C["border"])
        prov_row.grid(row=1, column=0, padx=14, pady=(8, 4), sticky="ew")
        prov_row.grid_columnconfigure(3, weight=1)
        _label(prov_row, "Провайдер:", 12).grid(row=0, column=0, padx=(14, 6), pady=10)
        self._pay_provider_var = tk.StringVar(value="stripe")
        for col, (lbl, val) in enumerate([
            ("💳 Stripe", "stripe"), ("🅿️ PayPal", "paypal"),
            ("🪙 USDT TRC20", "usdt_trc20"), ("⚡ Binance Pay", "binance_pay"),
        ], 1):
            ctk.CTkRadioButton(
                prov_row, text=lbl, variable=self._pay_provider_var, value=val,
                font=ctk.CTkFont(family=FF, size=12),
            ).grid(row=0, column=col, padx=12, pady=10, sticky="w")
        _label(prov_row, "Язык:", 12).grid(row=0, column=5, padx=(14, 6), pady=10)
        self._pay_lang_var = tk.StringVar(value="python")
        for col, (lbl, val) in enumerate([
            ("Python", "python"), ("JavaScript", "javascript"), ("PHP", "php"),
        ], 6):
            ctk.CTkRadioButton(
                prov_row, text=lbl, variable=self._pay_lang_var, value=val,
                font=ctk.CTkFont(family=FF, size=12),
            ).grid(row=0, column=col, padx=8, pady=10, sticky="w")

        # ── Информационные карточки ──────────────────────────────────────────
        info_scroll = ctk.CTkScrollableFrame(f, fg_color=C["bg"], corner_radius=0)
        info_scroll.grid(row=2, column=0, sticky="nsew", padx=14, pady=4)
        info_scroll.grid_columnconfigure((0,1), weight=1)
        self._pay_info_scroll = info_scroll

        cards_data = [
            ("💳  Stripe", "#635BFF",
             "Мировой лидер.\nПоддержка 135+ валют.\nWebhooks, 3DS2, Radar fraud.\nSAQ A / D compliance."),
            ("🅿️  PayPal", "#003087",
             "1.5B+ пользователей.\nOrders API v2.\nSubscriptions, IPN/Webhooks.\nСоздание счетов."),
            ("🪙  USDT TRC20", "#26A17B",
             "Крипто без KYC.\nTRON network, 1–2 сек.\nМинимальные комиссии.\nBinance Pay API."),
            ("🔒  Безопасность", "#DC2626",
             "3DS2 аутентификация.\nWebhook-подписи.\nIdempotency keys.\nPCI DSS соответствие."),
        ]
        for i, (title, color, body) in enumerate(cards_data):
            card = _card(info_scroll)
            card.grid(row=i//2, column=i%2, padx=8, pady=6, sticky="ew", ipadx=6, ipady=6)
            _label(card, title, 13, bold=True, color=color).pack(anchor="w", padx=14, pady=(10,2))
            _label(card, body, 11, color=C["txt2"]).pack(anchor="w", padx=14, pady=(0,10))

        return f

    def _refresh_payment(self) -> None:
        """Обновление при переходе на вкладку платежей."""
        pass  # статичный контент, обновление не нужно

    def _pay_codegen(self) -> None:
        """Генерировать код интеграции через PaymentAgent."""
        provider = getattr(self, "_pay_provider_var", None)
        lang     = getattr(self, "_pay_lang_var", None)
        prov_val = provider.get() if provider else "stripe"
        lang_val = lang.get() if lang else "python"
        self._q.put({"action": "update_status", "text": f"⚡ Генерирую {prov_val} код..."})

        def _run():
            try:
                from agents.payment_agent import PaymentAgent
                code = PaymentAgent.get().generate_payment_integration(prov_val, lang_val)
                self._q.put({"action": "_pay_show_code",
                             "text": code, "title": f"{prov_val.title()} / {lang_val}"})
            except Exception as ex:
                self._q.put({"action": "update_status", "text": f"⚠️ {ex}"})
        threading.Thread(target=_run, daemon=True).start()

    def _pay_invoice(self) -> None:
        """Диалог создания счёта."""
        import tkinter as _tk
        dlg = _tk.Toplevel(self._root)
        dlg.title("📄 Создать счёт")
        dlg.geometry("520x440")
        dlg.configure(bg=C["bg"])
        dlg.grab_set()
        _label(dlg, "📄 Выставить счёт клиенту", 15, bold=True).pack(padx=16, pady=(16,8), anchor="w")
        fields = [
            ("Имя клиента",   "client_name",  "John Doe"),
            ("Email клиента", "client_email", "john@example.com"),
            ("Описание",      "desc",         "Разработка веб-приложения"),
            ("Сумма (USD)",    "amount",       "500"),
        ]
        entries = {}
        for lbl, key, ph in fields:
            _label(dlg, lbl+":", 11, color=C["txt2"]).pack(padx=16, anchor="w")
            ent = ctk.CTkEntry(dlg, placeholder_text=ph,
                               font=ctk.CTkFont(family=FF, size=12),
                               width=480, height=30, corner_radius=6,
                               fg_color=C["input_bg"], border_width=0)
            ent.pack(padx=16, pady=(0,6), fill="x")
            entries[key] = ent
        result_lbl = _label(dlg, "", 11, color=C["txt2"])
        result_lbl.pack(padx=16, pady=4, anchor="w")

        def _create():
            vals = {k: e.get().strip() for k, e in entries.items()}
            if not vals["client_name"] or not vals["amount"]:
                result_lbl.configure(text="⚠️ Заполните имя и сумму!", text_color=C["error"])
                return
            result_lbl.configure(text="⏳ Создаю счёт...", text_color=C["txt2"])
            def _run():
                try:
                    from agents.payment_agent import PaymentAgent
                    inv = PaymentAgent.get().create_invoice(
                        client_name=vals["client_name"],
                        client_email=vals.get("client_email",""),
                        items=[{"description": vals.get("desc","Услуги"),
                                "amount": float(vals.get("amount","0") or 0),
                                "quantity": 1}],
                        currency="USD",
                    )
                    inv_id = getattr(inv, "id", "N/A")
                    total  = inv.total if hasattr(inv,"total") else vals.get("amount","0")
                    self._q.put({"action": "_pay_invoice_result", "lbl": result_lbl,
                                 "text": f"✅ Счёт создан!  ID: {inv_id}  |  Сумма: ${total}"})
                except Exception as ex:
                    self._q.put({"action": "_pay_invoice_result", "lbl": result_lbl,
                                 "text": f"⚠️ Ошибка: {ex}"})
            threading.Thread(target=_run, daemon=True).start()

        _btn(dlg, "💾 Создать счёт", _create, color=C["success"], width=130, height=32).pack(pady=8)
        _btn(dlg, "✕ Закрыть", dlg.destroy, color=C["txt2"], width=90, height=30).pack()

    def _pay_webhooks(self) -> None:
        """Показать инструкцию по настройке вебхуков."""
        import tkinter as _tk, tkinter.scrolledtext as _st
        dlg = _tk.Toplevel(self._root)
        dlg.title("📊 Настройка вебхуков")
        dlg.geometry("680x480")
        dlg.configure(bg=C["bg"])
        _label(dlg, "📊 Настройка Webhook", 15, bold=True).pack(padx=16, pady=(14,6), anchor="w")
        guide = """STRIPE WEBHOOK:
  1. Получите секрет: stripe.com → Developers → Webhooks
  2. Установите STRIPE_WEBHOOK_SECRET в .env
  3. Эндпоинт: POST /stripe/webhook
  4. Верификация: stripe.WebhookSignature.verify(payload, sig, secret)

PAYPAL IPN / Webhooks:
  1. developer.paypal.com → My Apps → Webhooks
  2. События: PAYMENT.CAPTURE.COMPLETED, CHECKOUT.ORDER.APPROVED
  3. Верификация: сравнить transmission-sig с HMAC-SHA256

BINANCE PAY:
  1. Merchant → API → Webhook URL
  2. Подпись: HMAC-SHA512 от payload
  3. Верифицировать header: BinancePay-Signature

БЕЗОПАСНОСТЬ:
  ✅ Всегда проверяй подписи — никогда не доверяй payload без верификации
  ✅ Idempotency: храни payment_intent/order_id и проверяй дубликаты
  ✅ HTTPS только — никогда HTTP для production
  ✅ Replay attack protection: проверяй timestamp (< 5 мин)
"""
        st = _st.ScrolledText(dlg, font=("Consolas", 11), bg=C["input_bg"], relief="flat",
                              bd=4, padx=8, pady=6, wrap="word")
        st.pack(fill="both", expand=True, padx=16, pady=4)
        st.insert("1.0", guide)
        st.configure(state="disabled")
        _btn(dlg, "✕ Закрыть", dlg.destroy, color=C["txt2"], width=90, height=30).pack(pady=10)

    def _show_pay_code(self, text: str, title: str) -> None:
        """Показать сгенерированный код платёжной интеграции."""
        import tkinter as _tk, tkinter.scrolledtext as _st
        dlg = _tk.Toplevel(self._root)
        dlg.title(f"⚡ Код интеграции — {title}")
        dlg.geometry("780x600")
        dlg.configure(bg=C["bg"])
        _label(dlg, f"⚡ {title} — Интеграция", 13, bold=True).pack(
            padx=16, pady=(14,4), anchor="w")
        st = _st.ScrolledText(dlg, font=("Consolas", 11), bg="#1e1e2e", fg="#d4d4d4",
                              relief="flat", bd=0, padx=10, pady=8, wrap="none")
        st.pack(fill="both", expand=True, padx=16, pady=4)
        st.insert("1.0", text)
        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(pady=10)
        def _copy():
            dlg.clipboard_clear()
            dlg.clipboard_append(text)
            self._q.put({"action": "update_status", "text": "✅ Код скопирован!"})
        _btn(btn_row, "📋 Копировать", _copy,       color=C["success"], width=120, height=30).pack(side="left", padx=6)
        _btn(btn_row, "✕ Закрыть",     dlg.destroy, color=C["txt2"],    width=90,  height=30).pack(side="left", padx=6)

    # ══════════════════════════════════════════════════════════════════════════

    def _tab_auth(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=C["bg"], corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        _label(f, "🔐  Авторизация и Сервисы", 18, bold=True).grid(
            row=0, padx=24, pady=(20, 8), sticky="w")
        btns = ctk.CTkFrame(f, fg_color="transparent")
        btns.grid(row=1, padx=16, pady=6, sticky="w")
        _btn(btns, "🌐 Браузер-вход", self._browser_auth_dlg, width=155).pack(side="left", padx=4)
        _btn(btns, "🔑 Добавить API ключ", self._add_key_dlg,
             color=C["success"], width=152).pack(side="left", padx=4)
        _label(f, "API ключи:", 12, color=C["txt2"]).grid(
            row=4, padx=24, pady=(14, 2), sticky="w")
        self._keys_scroll = ctk.CTkScrollableFrame(f, height=220)
        self._keys_scroll.grid(row=5, column=0, sticky="ew", padx=16, pady=4)
        return f

    def _tab_settings(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self._content, fg_color=C["bg"], corner_radius=0)
        f.grid_columnconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(f, fg_color=C["bg"], corner_radius=0)
        scroll.grid(row=0, column=0, sticky="nsew")
        f.grid_rowconfigure(0, weight=1)
        scroll.grid_columnconfigure(0, weight=1)
        _label(scroll, "⚙️  Настройки", 18, bold=True).grid(
            row=0, padx=24, pady=(20, 12), sticky="w")
        self._settings_entries: Dict[str, ctk.CTkEntry] = {}
        sections = [
            ("🧠 LLM Провайдеры", [
                ("DeepSeek API Key",  "DEEPSEEK_API_KEY",   True),
                ("Claude API Key",    "ANTHROPIC_API_KEY",  True),
                ("Groq API Key",      "GROQ_API_KEY",       True),
                ("OpenAI API Key",    "OPENAI_API_KEY",     True),
                ("Gemini API Key",    "GOOGLE_API_KEY",     True),
                ("xAI Grok Key",      "XAI_API_KEY",        True),
                ("Ollama URL",        "OLLAMA_URL",         False),
            ]),
            ("📱 Telegram", [
                ("Bot Token",  "TELEGRAM_BOT_TOKEN", True),
                ("Chat ID",    "TELEGRAM_CHAT_ID",   False),
            ]),
            ("📈 Bybit", [
                ("API Key",      "BYBIT_API_KEY",     True),
                ("API Secret",   "BYBIT_API_SECRET",  True),
                ("Testnet",      "BYBIT_TESTNET",     False),
            ]),
            ("💳 Платёжные системы", [
                ("Stripe Secret Key",      "STRIPE_SECRET_KEY",      True),
                ("Stripe Publishable Key", "STRIPE_PUBLISHABLE_KEY", True),
                ("Stripe Webhook Secret",  "STRIPE_WEBHOOK_SECRET",  True),
                ("PayPal Client ID",       "PAYPAL_CLIENT_ID",       True),
                ("PayPal Secret",          "PAYPAL_SECRET",          True),
                ("TRON Wallet (USDT)",     "CRYPTO_WALLET_TRON",     False),
                ("Binance Pay API Key",    "BINANCE_PAY_API_KEY",    True),
                ("Binance Pay Secret",     "BINANCE_PAY_SECRET",     True),
            ]),
        ]
        row_i = 1
        for sec_name, fields in sections:
            card = _card(scroll)
            card.grid(row=row_i, column=0, padx=14, pady=6, sticky="ew")
            card.grid_columnconfigure(1, weight=1)
            row_i += 1
            _label(card, sec_name, 13, bold=True).grid(
                row=0, column=0, columnspan=2, padx=14, pady=(10, 4), sticky="w")
            for fi, (lbl, key, is_pw) in enumerate(fields, 1):
                _label(card, lbl, 12, color=C["txt2"]).grid(
                    row=fi, column=0, padx=14, pady=3, sticky="w")
                current = os.getenv(key, "")
                ent = ctk.CTkEntry(
                    card, show="●" if is_pw and current else "",
                    font=ctk.CTkFont(family=FF, size=12),
                    placeholder_text=key, width=320, height=30,
                    corner_radius=6, fg_color=C["input_bg"], border_width=0,
                )
                if current:
                    ent.insert(0, "●●●●●●●●" if is_pw else current)
                ent.grid(row=fi, column=1, padx=(0, 14), pady=3, sticky="ew")
                self._settings_entries[key] = ent
            _btn(card, "💾 Сохранить",
                 lambda s=sec_name, fds=fields: self._save_settings(fds),
                 width=110, height=28, color=C["accent"]).grid(
                row=len(fields)+1, column=1, padx=(0, 14), pady=(4, 10), sticky="e")

        # ── Backup-карточка ────────────────────────────────────────────────
        bk_card = _card(scroll)
        bk_card.grid(row=row_i, column=0, padx=14, pady=6, sticky="ew")
        bk_card.grid_columnconfigure(1, weight=1)
        _label(bk_card, "💾 Резервные копии", 13, bold=True).grid(
            row=0, column=0, columnspan=2, padx=14, pady=(10, 4), sticky="w")
        _label(bk_card,
               "Автобэкап (daemon: каждый день в 03:00) или ручной запуск.",
               11, color=C["txt2"]).grid(row=1, column=0, columnspan=2, padx=14, pady=(0,4), sticky="w")
        self._backup_status = _label(bk_card, "", 11, color=C["txt2"])
        self._backup_status.grid(row=2, column=0, columnspan=2, padx=14, pady=(0,4), sticky="w")
        btn_row_bk = ctk.CTkFrame(bk_card, fg_color="transparent")
        btn_row_bk.grid(row=3, column=0, columnspan=2, padx=14, pady=(4,10), sticky="w")
        _btn(btn_row_bk, "📦 Создать бэкап",  self._run_backup,
             color=C["accent"],  width=138, height=28).pack(side="left", padx=4)
        _btn(btn_row_bk, "📋 Список бэкапов", self._list_backups,
             color=C["txt2"],    width=130, height=28).pack(side="left", padx=4)

        return f

    def _run_backup(self) -> None:
        """Запустить резервное копирование в фоне."""
        self._q.put({"action": "update_status", "text": "⏳ Создаю бэкап..."})
        if hasattr(self, "_backup_status"):
            self._backup_status.configure(text="⏳ Создаю резервную копию...", text_color=C["txt2"])

        def _do():
            try:
                from scripts.backup import create_backup
                arch = create_backup()
                size_mb = arch.stat().st_size / 1_048_576
                msg = f"✅ {arch.name}  ({size_mb:.1f} MB)"
                self._q.put({"action": "_backup_done", "text": msg, "ok": True})
            except Exception as e:
                self._q.put({"action": "_backup_done", "text": f"❌ {e}", "ok": False})
        threading.Thread(target=_do, daemon=True).start()

    def _list_backups(self) -> None:
        """Показать список бэкапов в диалоге."""
        import tkinter as _tk
        dlg = _tk.Toplevel(self._root)
        dlg.title("📋 Список бэкапов")
        dlg.geometry("580x340")
        dlg.configure(bg=C["bg"])
        dlg.grab_set()
        _label(dlg, "📋 Резервные копии", 15, bold=True).pack(padx=16, pady=(14,6), anchor="w")
        import tkinter.scrolledtext as _st
        st = _st.ScrolledText(dlg, font=("Consolas", 11), bg=C["input_bg"],
                              relief="flat", bd=4, padx=8, pady=6)
        st.pack(fill="both", expand=True, padx=16, pady=4)
        try:
            from pathlib import Path as _P
            backup_dir = _P(__file__).parent.parent / "backups"
            archives = sorted(
                backup_dir.glob("personal_ai_backup_*.tar.gz"),
                key=lambda p: p.stat().st_mtime, reverse=True
            ) if backup_dir.exists() else []
            if archives:
                import datetime as _dt
                lines = [f"Найдено бэкапов: {len(archives)}\n\n"]
                for a in archives:
                    sz = a.stat().st_size / 1_048_576
                    ts = _dt.datetime.fromtimestamp(a.stat().st_mtime).strftime("%d.%m.%Y %H:%M")
                    lines.append(f"  {ts}  |  {sz:5.1f} MB  |  {a.name}")
                st.insert("1.0", "\n".join(lines))
            else:
                st.insert("1.0", "Бэкапов нет.\nЗапустите «Создать бэкап» для первого архива.")
        except Exception as e:
            st.insert("1.0", f"Ошибка: {e}")
        st.configure(state="disabled")
        _btn(dlg, "✕ Закрыть", dlg.destroy, color=C["txt2"], width=90, height=30).pack(pady=10)

    # ══════════════════════════════════════════════════════════════════════════
    # НАВИГАЦИЯ
    # ══════════════════════════════════════════════════════════════════════════

    def _switch(self, key: str) -> None:
        for k, tab in self._tabs.items():
            tab.grid_remove()
        self._tabs[key].grid(row=0, column=0, sticky="nsew")
        self._current_tab = key
        for k, btn in self._nav.items():
            btn.configure(fg_color=C["sidebar_sel"] if k == key else "transparent",
                          text_color="#FFFFFF" if k == key else C["sidebar_txt"])
        if key == "dashboard":
            self._refresh_dashboard()
        elif key == "agents":
            self._render_agents()
        elif key == "task":
            self._mount_task_panel()
        elif key == "projects":
            self._render_projects()
        elif key == "freelance":
            self._refresh_freelance()
        elif key == "payment":
            self._refresh_payment()
        elif key == "browser":
            self._mount_browser_panel()
        elif key == "auth":
            self._render_auth()
        elif key == "trading":
            self._refresh_trading()

    # ══════════════════════════════════════════════════════════════════════════
    # ОЧЕРЕДЬ СОБЫТИЙ (THREAD-SAFE)
    # ══════════════════════════════════════════════════════════════════════════

    def _start_queue(self) -> None:
        """Обработать все события из фоновых потоков."""
        try:
            while True:
                item = self._q.get_nowait()
                action = item.get("action")

                if action == "chat":
                    tag = item.get("tag", "")
                    role = "user" if tag == "user" else "bot"
                    self._chat_add(role, item.get("text", ""), tag=tag)

                elif action == "step_update":
                    self._update_step(item.get("text", ""))

                elif action == "replace_thinking":
                    self._replace_thinking(item.get("text", ""))

                elif action == "unblock":
                    self._unblock_input()

                elif action == "add_tokens":
                    self._session_tokens += item.get("count", 0)
                    self._update_token_display()

                elif action == "update_status":
                    self._sb_status.configure(text=item.get("text", ""))

                elif action == "update_provider":
                    self._provider_lbl.configure(text=item.get("text", ""))

                elif action == "trade_log":
                    self._trade_log_append(item.get("text", ""))

                elif action == "update_trade_cards":
                    data = item.get("data", {})
                    for key, val in data.items():
                        if key in self._trade_cards:
                            self._trade_cards[key].configure(text=str(val))

                elif action == "_backup_done":
                    ok   = item.get("ok", False)
                    text = item.get("text", "")
                    self._q.put({"action": "update_status",
                                 "text": "✅ Бэкап готов" if ok else "❌ Бэкап провалился"})
                    try:
                        if hasattr(self, "_backup_status"):
                            self._backup_status.configure(
                                text=text,
                                text_color=C["success"] if ok else C["error"],
                            )
                    except Exception:
                        pass

                elif action == "_update_daemon_lbl":
                    try:
                        self._daemon_lbl.configure(
                            text=item.get("text", ""),
                            text_color=item.get("color", "#64748B"),
                        )
                    except Exception:
                        pass

                elif action == "_fl_render_jobs":
                    self._render_fl_jobs(
                        item.get("jobs", []),
                        item.get("error", ""),
                    )

                elif action == "_fl_estimate_result":
                    lbl = item.get("lbl")
                    if lbl:
                        try:
                            lbl.configure(text=item.get("text",""), text_color=C["txt2"])
                        except Exception:
                            pass

                elif action == "_fl_stats_result":
                    lbl = item.get("lbl")
                    if lbl:
                        try:
                            lbl.configure(text=item.get("text",""), text_color=C["txt2"])
                        except Exception:
                            pass

                elif action == "_fl_show_proposal":
                    self._show_fl_proposal(
                        item.get("text",""),
                        item.get("job_title",""),
                    )

                elif action == "_pay_show_code":
                    self._show_pay_code(
                        item.get("text",""),
                        item.get("title",""),
                    )
                    self._q.put({"action": "update_status", "text": "✅ Код готов"})

                elif action == "_pay_invoice_result":
                    lbl = item.get("lbl")
                    if lbl:
                        try:
                            lbl.configure(text=item.get("text",""),
                                          text_color=C["success"] if "✅" in item.get("text","") else C["error"])
                        except Exception:
                            pass

        except queue.Empty:
            pass
        finally:
            self._root.after(100, self._start_queue)

    # ══════════════════════════════════════════════════════════════════════════
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ══════════════════════════════════════════════════════════════════════════

    def _render_agents(self) -> None:
        for w in self._agents_scroll.winfo_children():
            w.destroy()
        if not self._agents:
            _label(self._agents_scroll, "Нет зарегистрированных агентов.", 13,
                   color=C["txt2"]).grid(padx=20, pady=40)
            return
        ICON = {
            "coder": "🖊️", "project_creator": "📁", "trading": "📈",
            "telegram": "📱", "analyzer": "🔍", "search": "🌐",
            "math": "🧮", "news": "📰", "planner": "📋",
            "summarizer": "📄", "image": "🖼️", "monitor": "👁️",
            "code_runner": "▶️", "self_training": "🎓", "key_manager": "🔑",
            "task_executor": "⚡", "browser": "🌐",
            "freelance": "💼", "payment": "💳",
        }
        for i, (name, agent) in enumerate(self._agents.items()):
            info   = agent.info() if hasattr(agent, "info") else None
            desc   = info.description if info else ""
            status = agent.get_status() if hasattr(agent, "get_status") else "unknown"
            sc = C["success"] if status == "idle" else C["accent"] if status == "running" else C["error"]
            card = _card(self._agents_scroll)
            card.grid(row=i, column=0, padx=6, pady=5, sticky="ew")
            card.grid_columnconfigure(1, weight=1)
            _label(card, ICON.get(name, "🤖"), 20).grid(row=0, column=0, rowspan=2, padx=(14,8), pady=14)
            _label(card, name, 14, bold=True).grid(row=0, column=1, sticky="w", pady=(12, 0))
            _label(card, desc[:80], 11, color=C["txt2"]).grid(row=1, column=1, sticky="w", pady=(0, 12))
            _label(card, f"● {status}", 11, color=sc).grid(row=0, column=2, padx=8, sticky="ne", pady=(12, 0))
            btns = ctk.CTkFrame(card, fg_color="transparent")
            btns.grid(row=0, column=3, rowspan=2, padx=14)
            _btn(btns, "▶ Старт", lambda n=name: self._agent_start(n),
                 color=C["success"], width=72, height=28).pack(side="left", padx=2)
            _btn(btns, "■ Стоп", lambda n=name: self._agent_stop(n),
                 color=C["error"], width=72, height=28).pack(side="left", padx=2)
            _btn(btns, "📋 Логи", lambda n=name: self._agent_logs(n),
                 color=C["txt2"], width=72, height=28).pack(side="left", padx=2)

    def _render_projects(self) -> None:
        for w in self._proj_scroll.winfo_children():
            w.destroy()

        # Поиск
        search_q = ""
        if hasattr(self, "_proj_search"):
            search_q = self._proj_search.get().strip().lower()

        # Из памяти
        db_projects: list = []
        try:
            from memory.memory_store import MemoryStore
            db_projects = MemoryStore.get().get_projects() or []
        except Exception:
            pass

        # Из файловой системы
        dir_projects: list = []
        try:
            for p in cfg.PROJECTS_DIR.iterdir():
                if p.is_dir() and p.name != "__pycache__":
                    dir_projects.append({
                        "name": p.name,
                        "description": "Проект в папке",
                        "path": str(p),
                        "_source": "fs",
                    })
        except Exception:
            pass

        # Склеиваем, убираем дубли по имени
        seen: set = set()
        all_projects: list = []
        for p in list(db_projects) + dir_projects:
            key = p.get("name", "").lower()
            if key and key not in seen:
                seen.add(key)
                all_projects.append(p)

        # Фильтр поиска
        if search_q:
            all_projects = [
                p for p in all_projects
                if search_q in p.get("name", "").lower()
                or search_q in p.get("description", "").lower()
            ]

        if not all_projects:
            _label(self._proj_scroll,
                   "Нет проектов. Создай через чат или кнопку «+ Проект»." if not search_q
                   else f"Ничего не найдено по запросу «{search_q}».",
                   13, color=C["txt2"]).grid(padx=20, pady=40)
            return

        for i, p in enumerate(all_projects[:50]):
            card = _card(self._proj_scroll)
            card.grid(row=i, column=0, padx=6, pady=5, sticky="ew")
            card.grid_columnconfigure(0, weight=1)

            # ── Иконка + имя ──────────────────────────────────────────────────
            name_row = ctk.CTkFrame(card, fg_color="transparent")
            name_row.grid(row=0, column=0, padx=14, pady=(10, 2), sticky="ew")
            name_row.grid_columnconfigure(0, weight=1)

            src_tag = "💾" if p.get("_source") == "fs" else "🗂"
            _label(name_row, f"📁  {p['name']}", 14, bold=True).grid(
                row=0, column=0, sticky="w")
            _label(name_row, src_tag, 11, color=C["txt2"]).grid(
                row=0, column=1, padx=(8, 0), sticky="e")

            # ── Описание ─────────────────────────────────────────────────────
            desc = p.get("description", "")
            if desc:
                _label(card, desc[:120] + ("…" if len(desc) > 120 else ""),
                       11, color=C["txt2"]).grid(
                    row=1, column=0, padx=14, pady=(0, 4), sticky="w")

            # ── Метаданные ────────────────────────────────────────────────────
            meta_parts = []
            if p.get("created_at"):
                try:
                    from datetime import datetime as _dt
                    ts = p["created_at"]
                    if isinstance(ts, (int, float)):
                        meta_parts.append(_dt.fromtimestamp(ts).strftime("%d.%m.%Y"))
                    elif isinstance(ts, str):
                        meta_parts.append(ts[:10])
                except Exception:
                    pass
            if p.get("path"):
                meta_parts.append(f"📂 {str(p['path'])[-40:]}")
            if p.get("tasks"):
                meta_parts.append(f"📋 {len(p['tasks'])} задач")
            if meta_parts:
                _label(card, "  ·  ".join(meta_parts), 10, color=C["txt2"]).grid(
                    row=2, column=0, padx=14, pady=(0, 4), sticky="w")

            # ── Кнопки действий ───────────────────────────────────────────────
            btns = ctk.CTkFrame(card, fg_color="transparent")
            btns.grid(row=3, column=0, padx=10, pady=(2, 10), sticky="w")

            _btn(btns, "📂 Открыть",
                 lambda proj=p: self._project_details_dlg(proj),
                 color=C["accent"], width=100, height=28).pack(side="left", padx=2)

            _btn(btns, "✏ Изменить",
                 lambda proj=p: self._project_edit_dlg(proj),
                 color=C["warning"], width=96, height=28).pack(side="left", padx=2)

            if not p.get("_source") == "fs":
                _btn(btns, "🗑 Удалить",
                     lambda proj=p: self._project_delete(proj),
                     color=C["error"], width=90, height=28).pack(side="left", padx=2)

            _btn(btns, "💬 В чат",
                 lambda proj=p: self._project_to_chat(proj),
                 color="#7C3AED", width=80, height=28).pack(side="left", padx=2)

    def _render_auth(self) -> None:
        for w in self._keys_scroll.winfo_children():
            w.destroy()

        # ── Кнопки управления ────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(self._keys_scroll, fg_color="transparent")
        ctrl.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 8))
        _btn(ctrl, "+ Добавить ключ", self._add_key_dlg,
             color=C["success"], width=140, height=30).pack(side="left", padx=2)
        _btn(ctrl, "🔄 Обновить", self._render_auth,
             color=C["txt2"], width=90, height=30).pack(side="left", padx=2)
        _btn(ctrl, "🔍 Проверить все", self._validate_keys,
             color=C["accent"], width=130, height=30).pack(side="left", padx=2)

        # ── Список ключей ────────────────────────────────────────────────────
        try:
            from core.secret_manager import SecretManager
            keys = SecretManager.get().list_keys()
        except Exception:
            keys = []

        # Также показываем ключи из .env
        env_keys = self._get_env_keys()
        all_keys = list(keys) + [k for k in env_keys if k["key"] not in
                                  {x.get("key") for x in keys}]

        if not all_keys:
            _label(self._keys_scroll, "Нет сохранённых ключей. Добавь через кнопку выше.",
                   12, color=C["txt2"]).grid(row=1, column=0, padx=20, pady=20)
            return

        for i, k in enumerate(all_keys[:30]):
            row = ctk.CTkFrame(self._keys_scroll, fg_color=C["card"],
                               corner_radius=8, border_width=1, border_color=C["border"])
            row.grid(row=i + 1, column=0, sticky="ew", padx=4, pady=2)
            row.grid_columnconfigure(1, weight=1)

            service = k.get("service") or k.get("provider") or "—"
            key_name = k.get("key", "?")
            has_value = bool(k.get("value") or k.get("masked"))
            icon = "🔑" if has_value else "⚠"
            color = C["txt"] if has_value else C["warning"]

            _label(row, f"{icon} {key_name}", 11, bold=True, color=color).grid(
                row=0, column=0, padx=(12, 8), pady=8, sticky="w")
            _label(row, f"[{service}]", 10, color=C["txt2"]).grid(
                row=0, column=1, padx=4, sticky="w")

            # Кнопка удаления
            if not k.get("_env"):   # env-ключи нельзя удалить отсюда
                _btn(row, "🗑", lambda kn=key_name: self._delete_key(kn),
                     color=C["error"], width=32, height=28).grid(
                    row=0, column=2, padx=(0, 8), pady=4, sticky="e")

    def _get_env_keys(self) -> list:
        """Список ключей из .env файла (только имена)."""
        result = []
        KEY_NAMES = [
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY",
            "GOOGLE_API_KEY", "DEEPSEEK_API_KEY", "TOGETHER_API_KEY",
            "XAI_API_KEY", "MISTRAL_API_KEY", "PERPLEXITY_API_KEY",
            "TELEGRAM_BOT_TOKEN", "BYBIT_API_KEY", "BYBIT_API_SECRET",
        ]
        import os
        for name in KEY_NAMES:
            val = os.environ.get(name, "")
            result.append({
                "key": name,
                "service": name.replace("_API_KEY", "").replace("_", " ").title(),
                "value": val[:4] + "●●●●" if val else "",
                "_env": True,
            })
        return result

    def _add_key_dlg(self) -> None:
        """Диалог добавления нового API-ключа."""
        import tkinter as _tk
        dlg = _tk.Toplevel(self._root)
        dlg.title("Добавить API-ключ")
        dlg.geometry("480x260")
        dlg.configure(bg=C["bg"])
        dlg.grab_set()
        _label(dlg, "🔑 Новый API-ключ", 15, bold=True).pack(
            padx=16, pady=(16, 8), anchor="w")
        _label(dlg, "Название (например: OPENAI_API_KEY):", 11).pack(
            padx=16, anchor="w")
        name_e = ctk.CTkEntry(dlg, width=440, height=34, corner_radius=8)
        name_e.pack(padx=16, pady=4)
        _label(dlg, "Значение ключа:", 11).pack(padx=16, anchor="w")
        val_e = ctk.CTkEntry(dlg, width=440, height=34, corner_radius=8, show="●")
        val_e.pack(padx=16, pady=4)
        def _save():
            name = name_e.get().strip().upper()
            val  = val_e.get().strip()
            if not name or not val:
                return
            try:
                from core.secret_manager import SecretManager
                SecretManager.get().set(name, val)
            except Exception:
                pass
            # Также записываем в .env
            try:
                env_path = cfg.BASE_DIR / ".env"
                lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
                found = False
                for idx, line in enumerate(lines):
                    if line.startswith(f"{name}="):
                        lines[idx] = f"{name}={val}"
                        found = True
                        break
                if not found:
                    lines.append(f"{name}={val}")
                env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except Exception:
                pass
            dlg.destroy()
            self._render_auth()
        _btn(dlg, "💾 Сохранить", _save, color=C["success"], width=120, height=34).pack(pady=12)

    def _delete_key(self, key_name: str) -> None:
        import tkinter as _tk
        if not _tk.messagebox.askyesno(
            "Удалить ключ", f"Удалить ключ «{key_name}»?", parent=self._root
        ):
            return
        try:
            from core.secret_manager import SecretManager
            SecretManager.get().delete(key_name)
        except Exception:
            pass
        self._render_auth()

    def _validate_keys(self) -> None:
        """Запустить проверку всех ключей в фоне."""
        self._q.put({"action": "update_status", "text": "🔍 Проверка ключей..."})
        def _run():
            try:
                from brain.orchestrator import BrainOrchestrator
                km = BrainOrchestrator.get()._agents.get("key_manager")
                if km and hasattr(km, "validate_all_keys"):
                    statuses = km.validate_all_keys()
                    valid = sum(1 for s in statuses if s.valid)
                    self._q.put({"action": "update_status",
                                 "text": f"✅ Ключей OK: {valid}/{len(statuses)}"})
                    self._root.after(0, self._render_auth)
                else:
                    self._q.put({"action": "update_status", "text": "⚠ KeyManager недоступен"})
            except Exception as e:
                self._q.put({"action": "update_status", "text": f"❌ {e}"})
            self._root.after(5000, lambda: self._q.put(
                {"action": "update_status", "text": "● Работает"}))
        threading.Thread(target=_run, daemon=True).start()

    def _refresh_dashboard(self) -> None:
        try:
            from memory.memory_store import MemoryStore
            s = MemoryStore.get().stats()
            self._dsh["knowledge"].configure(text=str(s.get("knowledge", 0)))
            self._dsh["projects"].configure(text=str(s.get("projects", 0)))
            self._dsh["tasks"].configure(text=str(s.get("tasks_pending", 0)))
            self._dsh["agents"].configure(text=str(len(self._agents)))
        except Exception:
            pass
        # Фриланс-статистика
        try:
            from agents.freelance_agent import FreelanceAgent
            stats = FreelanceAgent.get().track_earnings()
            total = stats.get("total_usd", 0)
            # proposals count from DB
            proposals = 0
            try:
                proposals = len(FreelanceAgent.get()._db.get_proposals())
            except Exception:
                pass
            self._dsh["earnings"].configure(text=f"${total:,.0f}")
            self._dsh["proposals"].configure(text=str(proposals))
        except Exception:
            pass
        try:
            from brain.llm_router import LLMRouter
            report = LLMRouter.get().status_report()
            avail = [k for k, v in report.items() if v["available"]]
            self._llm_lbl.configure(
                text="✅ " + " · ".join(avail) if avail else "❌ Нет провайдеров",
                text_color=C["success"] if avail else C["error"]
            )
        except Exception:
            pass
        # Evolution stats
        try:
            parts = []
            from brain.chain_of_thought import ChainOfThoughtEngine
            s = ChainOfThoughtEngine.get().get_stats()
            parts.append(f"CoT: {s.get('cot',0)} runs")
            from memory.episodic_memory import EpisodicMemory
            s2 = EpisodicMemory.get().get_stats()
            parts.append(f"Episodic: {s2.get('total_episodes',0)} эпизодов")
            from core.task_queue import TaskQueue
            s3 = TaskQueue.get().get_stats()
            parts.append(f"Queue: {s3.get('pending',0)} в очереди")
            self._evo_lbl.configure(text="  ·  ".join(parts))
        except Exception:
            pass

    def _save_settings(self, fields: list) -> None:
        env_path = cfg.BASE_DIR / ".env"
        lines = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
        for lbl, key, is_pw in fields:
            ent = self._settings_entries.get(key)
            if not ent:
                continue
            val = ent.get().strip()
            if val.startswith("●"):
                continue  # маскированный пароль — не перезаписываем
            found = False
            for i, line in enumerate(lines):
                if line.startswith(f"{key}="):
                    lines[i] = f"{key}={val}"
                    found = True
                    break
            if not found and val:
                lines.append(f"{key}={val}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._q.put({"action": "update_status", "text": "✅ Настройки сохранены"})
        self._root.after(3000, lambda: self._q.put({
            "action": "update_status", "text": "● Работает"}))

    # ── Диалоги ───────────────────────────────────────────────────────────────

    def _create_project_dlg(self) -> None:
        import tkinter as _tk
        dlg = _tk.Toplevel(self._root)
        dlg.title("Создать проект")
        dlg.geometry("440x220")
        dlg.configure(bg=C["bg"])
        dlg.grab_set()
        _label(dlg, "📁 Название проекта:", 12).pack(padx=16, pady=(16, 4), anchor="w")
        name_ent = ctk.CTkEntry(dlg, font=ctk.CTkFont(family=FF, size=13),
                                width=400, height=36, corner_radius=8)
        name_ent.pack(padx=16, pady=4)
        _label(dlg, "Описание (опционально):", 12).pack(padx=16, pady=(8, 4), anchor="w")
        desc_ent = ctk.CTkEntry(dlg, font=ctk.CTkFont(family=FF, size=12),
                                width=400, height=32, corner_radius=8)
        desc_ent.pack(padx=16, pady=4)
        def _create():
            name = name_ent.get().strip()
            if name:
                self._q.put({"action": "chat", "tag": "user",
                             "text": f"создай проект {name}"})
                dlg.destroy()
        _btn(dlg, "✅ Создать", _create, width=120, height=34).pack(pady=12)

    def _new_subproject_dlg(self) -> None:
        import tkinter as _tk
        dlg = _tk.Toplevel(self._root)
        dlg.title("Новый подпроект")
        dlg.geometry("500x280")
        dlg.configure(bg=C["bg"])
        dlg.grab_set()
        _label(dlg, "🔀 Новый подпроект", 16, bold=True).pack(
            padx=16, pady=(16, 4), anchor="w")
        _label(dlg, "Подпроекты делят контекст с основным проектом и\n"
                    "автоматически получают соответствующие роли агентов.", 11,
               color=C["txt2"]).pack(padx=16, pady=(0, 12), anchor="w")
        _label(dlg, "Название подпроекта:", 12).pack(padx=16, pady=(4, 2), anchor="w")
        name_ent = ctk.CTkEntry(dlg, font=ctk.CTkFont(family=FF, size=13),
                                width=460, height=36, corner_radius=8)
        name_ent.pack(padx=16, pady=4)
        _label(dlg, "Цель подпроекта:", 12).pack(padx=16, pady=(8, 2), anchor="w")
        goal_ent = ctk.CTkEntry(dlg, font=ctk.CTkFont(family=FF, size=12),
                                width=460, height=32, corner_radius=8,
                                placeholder_text="Например: написать тесты, задокументировать API...")
        goal_ent.pack(padx=16, pady=4)
        def _create():
            name = name_ent.get().strip()
            goal = goal_ent.get().strip()
            if name:
                task = f"создай подпроект '{name}'"
                if goal:
                    task += f" с целью: {goal}"
                self._chat_add("user", task)
                threading.Thread(
                    target=lambda: self._q.put({
                        "action": "replace_thinking",
                        "text": self._call_brain(task)
                    }),
                    daemon=True
                ).start()
                dlg.destroy()
        _btn(dlg, "✅ Создать подпроект", _create,
             color="#7C3AED", width=170, height=34).pack(pady=12)

    # ── Проекты: диалоги ──────────────────────────────────────────────────────

    def _project_details_dlg(self, proj: dict) -> None:
        """Диалог просмотра деталей проекта."""
        import tkinter as _tk
        dlg = _tk.Toplevel(self._root)
        dlg.title(f"Проект: {proj.get('name', '—')}")
        dlg.geometry("600x500")
        dlg.configure(bg=C["bg"])
        dlg.grab_set()

        _label(dlg, f"📁 {proj.get('name', '—')}", 16, bold=True).pack(
            padx=16, pady=(16, 4), anchor="w")

        txt = _tk.Text(dlg, font=(FF, 11), bg=C["input_bg"],
                       relief="flat", bd=0, padx=12, pady=8, wrap="word",
                       highlightthickness=0)
        txt.pack(fill="both", expand=True, padx=16, pady=8)

        lines = []
        if proj.get("description"):
            lines.append(f"📝 Описание:\n{proj['description']}\n")
        if proj.get("path"):
            lines.append(f"📂 Путь:\n{proj['path']}\n")
        if proj.get("created_at"):
            lines.append(f"📅 Создан: {proj['created_at']}\n")
        if proj.get("tasks"):
            lines.append(f"📋 Задач: {len(proj['tasks'])}")
            for t in proj["tasks"][:10]:
                lines.append(f"   • {str(t)[:80]}")
            lines.append("")
        if proj.get("notes"):
            lines.append(f"🗒 Заметки:\n{proj['notes']}\n")

        # Если ничего нет — показываем всё что есть
        if not lines:
            for k, v in proj.items():
                if not k.startswith("_"):
                    lines.append(f"{k}: {v}")

        txt.insert("1.0", "\n".join(lines) if lines else "Нет дополнительных данных.")
        txt.configure(state="disabled")

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(pady=8)
        _btn(btn_row, "✏ Изменить",
             lambda: (dlg.destroy(), self._project_edit_dlg(proj)),
             color=C["warning"], width=110, height=32).pack(side="left", padx=4)
        _btn(btn_row, "💬 В чат",
             lambda: (dlg.destroy(), self._project_to_chat(proj)),
             color="#7C3AED", width=90, height=32).pack(side="left", padx=4)
        _btn(btn_row, "✕ Закрыть", dlg.destroy,
             color=C["txt2"], width=90, height=32).pack(side="left", padx=4)

    def _project_edit_dlg(self, proj: dict) -> None:
        """Диалог редактирования проекта."""
        import tkinter as _tk
        dlg = _tk.Toplevel(self._root)
        dlg.title(f"Изменить: {proj.get('name', '—')}")
        dlg.geometry("520x380")
        dlg.configure(bg=C["bg"])
        dlg.grab_set()

        _label(dlg, "✏  Редактирование проекта", 15, bold=True).pack(
            padx=16, pady=(16, 8), anchor="w")

        _label(dlg, "Название:", 12).pack(padx=16, pady=(4, 2), anchor="w")
        name_ent = ctk.CTkEntry(dlg, font=ctk.CTkFont(family=FF, size=13),
                                width=480, height=36, corner_radius=8)
        name_ent.pack(padx=16, pady=(0, 8))
        name_ent.insert(0, proj.get("name", ""))

        _label(dlg, "Описание:", 12).pack(padx=16, pady=(4, 2), anchor="w")
        desc_txt = _tk.Text(dlg, height=4, font=(FF, 12), bg=C["input_bg"],
                            relief="flat", bd=0, padx=8, pady=6, wrap="word",
                            highlightthickness=1, highlightbackground=C["border"])
        desc_txt.pack(fill="x", padx=16, pady=(0, 8))
        desc_txt.insert("1.0", proj.get("description", ""))

        _label(dlg, "Заметки:", 12).pack(padx=16, pady=(4, 2), anchor="w")
        notes_txt = _tk.Text(dlg, height=3, font=(FF, 12), bg=C["input_bg"],
                             relief="flat", bd=0, padx=8, pady=6, wrap="word",
                             highlightthickness=1, highlightbackground=C["border"])
        notes_txt.pack(fill="x", padx=16, pady=(0, 8))
        notes_txt.insert("1.0", proj.get("notes", ""))

        def _save():
            new_name = name_ent.get().strip()
            new_desc = desc_txt.get("1.0", "end").strip()
            new_notes = notes_txt.get("1.0", "end").strip()
            if not new_name:
                return
            try:
                from memory.memory_store import MemoryStore
                mem = MemoryStore.get()
                if hasattr(mem, "update_project"):
                    mem.update_project(proj.get("id") or proj.get("name"),
                                       name=new_name, description=new_desc,
                                       notes=new_notes)
                else:
                    # Обновляем через delete + re-save
                    if hasattr(mem, "delete_project"):
                        mem.delete_project(proj.get("id") or proj.get("name"))
                    if hasattr(mem, "save_project"):
                        mem.save_project({"name": new_name, "description": new_desc,
                                          "notes": new_notes})
            except Exception as e:
                _label(dlg, f"⚠ Ошибка: {e}", 11, color=C["error"]).pack(pady=4)
                return
            dlg.destroy()
            self._render_projects()
            self._q.put({"action": "update_status", "text": "✅ Проект обновлён"})
            self._root.after(3000, lambda: self._q.put(
                {"action": "update_status", "text": "● Работает"}))

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(pady=8)
        _btn(btn_row, "💾 Сохранить", _save,
             color=C["success"], width=120, height=34).pack(side="left", padx=4)
        _btn(btn_row, "✕ Отмена", dlg.destroy,
             color=C["txt2"], width=90, height=34).pack(side="left", padx=4)

    def _project_delete(self, proj: dict) -> None:
        """Удалить проект с подтверждением."""
        import tkinter as _tk
        name = proj.get("name", "—")
        if not _tk.messagebox.askyesno(
            "Удалить проект",
            f"Удалить проект «{name}»?\nЭто действие нельзя отменить.",
            parent=self._root,
        ):
            return
        try:
            from memory.memory_store import MemoryStore
            mem = MemoryStore.get()
            proj_id = proj.get("id") or proj.get("name")
            if hasattr(mem, "delete_project"):
                mem.delete_project(proj_id)
            else:
                _tk.messagebox.showwarning("Удаление", "Метод delete_project не реализован.",
                                           parent=self._root)
                return
        except Exception as e:
            _tk.messagebox.showerror("Ошибка удаления", str(e), parent=self._root)
            return
        self._render_projects()
        self._q.put({"action": "update_status", "text": f"🗑 Проект «{name}» удалён"})
        self._root.after(3000, lambda: self._q.put(
            {"action": "update_status", "text": "● Работает"}))

    def _project_to_chat(self, proj: dict) -> None:
        """Перейти в чат с контекстом проекта."""
        name = proj.get("name", "—")
        desc = proj.get("description", "")
        prompt = f"Расскажи о проекте «{name}»"
        if desc:
            prompt += f": {desc}"
        # Переключиться на чат
        self._switch("chat")
        # Вставить в поле ввода
        if hasattr(self, "_inp") and hasattr(self, "_ph"):
            self._inp.configure(state="normal")
            self._inp.delete("1.0", "end")
            self._inp.configure(fg=C["txt"])
            self._ph = False
            self._inp.insert("1.0", prompt)
            self._inp.focus_set()

    def _browser_auth_dlg(self) -> None:
        import tkinter as _tk
        dlg = _tk.Toplevel(self._root)
        dlg.title("Браузер-авторизация")
        dlg.geometry("420x200")
        dlg.configure(bg=C["bg"])
        dlg.grab_set()
        _label(dlg, "🌐 URL для авторизации:", 12).pack(padx=16, pady=(16, 4), anchor="w")
        url_ent = ctk.CTkEntry(dlg, font=ctk.CTkFont(family=FF, size=12),
                               width=380, height=32, corner_radius=8,
                               placeholder_text="https://example.com/login")
        url_ent.pack(padx=16, pady=4)
        def _go():
            url = url_ent.get().strip()
            if url:
                try:
                    from auth.browser_auth import BrowserAuth
                    BrowserAuth.get().open_for_auth(url)
                except Exception as e:
                    _label(dlg, f"Ошибка: {e}", 11, color=C["error"]).pack(pady=4)
        _btn(dlg, "🌐 Открыть", _go, width=120, height=32).pack(pady=8)

    def _add_key_dlg(self) -> None:
        import tkinter as _tk
        dlg = _tk.Toplevel(self._root)
        dlg.title("Добавить API ключ")
        dlg.geometry("440x220")
        dlg.configure(bg=C["bg"])
        dlg.grab_set()
        _label(dlg, "Сервис:", 12).pack(padx=16, pady=(16, 4), anchor="w")
        svc_ent = ctk.CTkEntry(dlg, font=ctk.CTkFont(family=FF, size=12),
                               width=400, height=32, corner_radius=8,
                               placeholder_text="openai / claude / groq / ...")
        svc_ent.pack(padx=16, pady=4)
        _label(dlg, "API Ключ:", 12).pack(padx=16, pady=(8, 4), anchor="w")
        key_ent = ctk.CTkEntry(dlg, show="●", font=ctk.CTkFont(family=FF, size=12),
                               width=400, height=32, corner_radius=8)
        key_ent.pack(padx=16, pady=4)
        def _save():
            svc = svc_ent.get().strip()
            key = key_ent.get().strip()
            if svc and key:
                try:
                    from core.secret_manager import SecretManager
                    SecretManager.get().store_key(svc, key)
                    dlg.destroy()
                except Exception as e:
                    _label(dlg, f"Ошибка: {e}", 11, color=C["error"]).pack(pady=4)
        _btn(dlg, "💾 Сохранить", _save, color=C["success"], width=120, height=32).pack(pady=8)

    def _agent_start(self, name: str) -> None:
        agent = self._agents.get(name)
        if agent and hasattr(agent, "start"):
            threading.Thread(target=agent.start, daemon=True).start()

    def _agent_stop(self, name: str) -> None:
        agent = self._agents.get(name)
        if agent and hasattr(agent, "stop"):
            threading.Thread(target=agent.stop, daemon=True).start()

    def _agent_logs(self, name: str) -> None:
        import tkinter as _tk
        dlg = _tk.Toplevel(self._root)
        dlg.title(f"Логи агента: {name}")
        dlg.geometry("700x500")
        dlg.configure(bg=C["bg"])
        txt = _tk.Text(dlg, font=(FF, 11), bg=C["input_bg"],
                       relief="flat", bd=0, padx=12, pady=8, wrap="word")
        txt.pack(fill="both", expand=True, padx=12, pady=12)
        try:
            log_file = cfg.LOGS_DIR / f"{name}.log"
            if log_file.exists():
                content = log_file.read_text(encoding="utf-8", errors="replace")
                txt.insert("1.0", content[-10000:])  # последние 10K символов
            else:
                txt.insert("1.0", f"Лог файл не найден: {log_file}")
        except Exception as e:
            txt.insert("1.0", f"Ошибка чтения логов: {e}")
        txt.configure(state="disabled")
        txt.see("end")

    def _email_hint(self) -> None:
        pass  # placeholder

    # ══════════════════════════════════════════════════════════════════════════
    # FALLBACK (без CustomTkinter)
    # ══════════════════════════════════════════════════════════════════════════

    def _build_tk(self) -> None:
        import tkinter as tk
        lbl = tk.Label(self._root, text="⚠️ CustomTkinter не установлен.\n\n"
                       "pip install customtkinter\n\nПерезапусти приложение.",
                       font=(FF, 14), bg="#F0F4F8", fg="#1E293B", justify="center")
        lbl.pack(expand=True)

    # ══════════════════════════════════════════════════════════════════════════
    # ПУБЛИЧНЫЙ API (для main.py)
    # ══════════════════════════════════════════════════════════════════════════

    def set_brain(self, brain) -> None:
        self._brain = brain
        self._q.put({"action": "update_status", "text": "● Готов"})

    def register_agent(self, name: str, agent: Any) -> None:
        self._agents[name] = agent

    def post(self, item: dict) -> None:
        """Внешний post из других потоков (например, TelegramAgent → GUI)."""
        self._q.put(item)

    def run(self) -> None:
        """Запустить главный цикл GUI."""
        try:
            self._root.mainloop()
        except KeyboardInterrupt:
            pass
