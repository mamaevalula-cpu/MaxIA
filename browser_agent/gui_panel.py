# -*- coding: utf-8 -*-
"""
browser_agent/gui_panel.py — Chrome-стиль панель браузер-агента.

Полный редизайн в стиле Google Chrome:
  • Вкладки с цветовой индикацией
  • Панель навигации (назад/вперёд/обновить/домой)
  • Omnibox — объединённая строка URL + поиск
  • Кнопка профиля (аватар)
  • Закладки
  • Плавные анимации и современный UI

Встраивается в gui/main_window.py:
    from browser_agent.gui_panel import BrowserPanel
    panel = BrowserPanel(parent_frame)
    panel.pack(fill="both", expand=True)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

log = logging.getLogger("browser_agent.gui")

try:
    import tkinter as tk
    from tkinter import ttk, font
    _TK_OK = True
except ImportError:
    _TK_OK = False

# ── Цветовая схема Chrome (Material Design) ─────────────────────────────────────
COLORS = {
    "bg":              "#FFFFFF",
    "bg_hover":        "#F1F3F4",
    "bg_active":       "#E8EAED",
    "surface":         "#F8F9FA",
    "surface_hover":   "#E8EAED",
    "tab_bg":          "#DEE1E6",
    "tab_active":      "#FFFFFF",
    "tab_hover":       "#E8EAED",
    "tab_line":        "#1A73E8",
    "omnibox_bg":      "#FFFFFF",
    "omnibox_border":  "#DADCE0",
    "omnibox_focus":   "#1A73E8",
    "txt_primary":     "#202124",
    "txt_secondary":   "#5F6368",
    "txt_white":       "#FFFFFF",
    "accent":          "#1A73E8",
    "accent_hover":    "#1557B0",
    "green":           "#34A853",
    "red":             "#EA4335",
    "yellow":          "#FBBC04",
    "border":          "#DADCE0",
    "divider":         "#E8EAED",
    "bookmark_bg":     "#FFFFFF",
    "bookmark_txt":    "#5F6368",
    "status_bg":       "#F8F9FA",
    "log_bg":          "#F8F9FA",
    "log_border":      "#E8EAED",
    "btn_icon":        "#5F6368",
    "badge_bg":        "#EA4335",
    "badge_txt":       "#FFFFFF",
}

# ── Шрифты ─────────────────────────────────────────────────────────────────────
def _get_fonts():
    if _TK_OK:
        try:
            default_font = font.nametofont("TkDefaultFont")
            family = default_font.actual("family")
        except Exception:
            family = "Segoe UI"
    else:
        family = "Segoe UI"
    return {
        "family": family,
        "tab":       (family, 12),
        "tab_bold":  (family, 12, "bold"),
        "omnibox":   (family, 13),
        "button":    (family, 11),
        "bookmark":  (family, 11),
        "status":    (family, 11),
        "log":       ("Consolas", 10),
        "title":     (family, 14, "bold"),
        "small":     (family, 9),
    }


class BrowserPanel:
    """Панель управления браузер-агентом в стиле Google Chrome."""

    def __init__(self, parent):
        if not _TK_OK:
            log.error("tkinter not available")
            return
        self._parent = parent
        self._agent = None
        self._fonts = _get_fonts()
        self._tabs = []
        self._active_tab = 0
        self._build_ui()

    def _agent_instance(self):
        if self._agent is None:
            try:
                from browser_agent.agent import BrowserAgent
                self._agent = BrowserAgent.get()
            except Exception as e:
                log.error("BrowserAgent import error: %s", e)
        return self._agent

    # ── Основной билдер ────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = self._parent
        root.configure(bg=COLORS["bg"])

        self._build_tab_bar(root)
        self._build_nav_bar(root)
        self._build_bookmark_bar(root)
        self._build_main_area(root)
        self._build_status_bar(root)

        self._add_tab("Новая вкладка")

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. Tab Bar (как в Chrome)
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_tab_bar(self, parent) -> None:
        self._tab_frame = tk.Frame(parent, bg=COLORS["surface"], height=36)
        self._tab_frame.pack(fill="x", padx=0, pady=(0, 0))
        self._tab_frame.pack_propagate(False)

        self._tabs_container = tk.Frame(self._tab_frame, bg=COLORS["surface"])
        self._tabs_container.pack(side="left", fill="both", expand=True)

        # Кнопка "+"
        self._new_tab_btn = tk.Label(
            self._tab_frame, text="+", font=self._fonts["tab_bold"],
            bg=COLORS["surface"], fg=COLORS["txt_secondary"],
            cursor="hand2", padx=8, pady=2,
        )
        self._new_tab_btn.pack(side="left", padx=(0, 2))
        self._new_tab_btn.bind("<Button-1>", lambda e: self._add_tab())
        self._new_tab_btn.bind("<Enter>", lambda e: self._new_tab_btn.configure(bg=COLORS["bg_hover"]))
        self._new_tab_btn.bind("<Leave>", lambda e: self._new_tab_btn.configure(bg=COLORS["surface"]))

        # Кнопка меню (⋮)
        self._menu_btn = tk.Label(
            self._tab_frame, text="⋮", font=self._fonts["tab_bold"],
            bg=COLORS["surface"], fg=COLORS["txt_secondary"],
            cursor="hand2", padx=8, pady=2,
        )
        self._menu_btn.pack(side="right", padx=(0, 4))
        self._menu_btn.bind("<Button-1>", lambda e: self._show_menu())
        self._menu_btn.bind("<Enter>", lambda e: self._menu_btn.configure(bg=COLORS["bg_hover"]))
        self._menu_btn.bind("<Leave>", lambda e: self._menu_btn.configure(bg=COLORS["surface"]))

    # ── Добавление / активация / закрытие вкладки ──────────────────────────────
    def _add_tab(self, title: str = "Новая вкладка") -> None:
        idx = len(self._tabs)
        tab_data = {"title": title, "url": ""}
        self._tabs.append(tab_data)

        is_active = (idx == self._active_tab)
        # Если это первая вкладка — она активна
        if len(self._tabs) == 1:
            is_active = True

        tab_frame = tk.Frame(
            self._tabs_container,
            bg=COLORS["tab_active"] if is_active else COLORS["tab_bg"],
            bd=0, highlightthickness=0,
        )
        tab_frame.pack(side="left", padx=(0, 0), pady=(4, 0), fill="y")

        # Синяя линия сверху (как Chrome)
        line = tk.Frame(
            tab_frame, bg=COLORS["tab_line"] if is_active else COLORS["tab_bg"],
            height=2, bd=0, highlightthickness=0,
        )
        line.pack(fill="x", side="top")

        bg_c = COLORS["tab_active"] if is_active else COLORS["tab_bg"]
        content = tk.Frame(tab_frame, bg=bg_c, bd=0)
        content.pack(fill="both", expand=True, padx=8, pady=(2, 4))

        icon_lbl = tk.Label(content, text="🌐", font=self._fonts["small"], bg=bg_c, fg=COLORS["txt_primary"])
        icon_lbl.pack(side="left", padx=(0, 4))

        title_lbl = tk.Label(content, text=title, font=self._fonts["tab"], bg=bg_c, fg=COLORS["txt_primary"])
        title_lbl.pack(side="left", padx=(0, 6))

        close_lbl = tk.Label(content, text="✕", font=self._fonts["small"], bg=bg_c, fg=COLORS["txt_secondary"], cursor="hand2", padx=2)
        close_lbl.pack(side="right")

        def _make_handlers(i):
            def on_enter(e):
                if i != self._active_tab:
                    tab_frame.configure(bg=COLORS["tab_hover"])
                    content.configure(bg=COLORS["tab_hover"])
                    icon_lbl.configure(bg=COLORS["tab_hover"])
                    title_lbl.configure(bg=COLORS["tab_hover"])
                    close_lbl.configure(bg=COLORS["tab_hover"])
            def on_leave(e):
                if i != self._active_tab:
                    tab_frame.configure(bg=COLORS["tab_bg"])
                    content.configure(bg=COLORS["tab_bg"])
                    icon_lbl.configure(bg=COLORS["tab_bg"])
                    title_lbl.configure(bg=COLORS["tab_bg"])
                    close_lbl.configure(bg=COLORS["tab_bg"])
            def on_click(e):
                self._activate_tab(i)
            def on_close(e):
                self._close_tab(i)
            return on_enter, on_leave, on_click, on_close

        eh = _make_handlers(idx)
        tab_frame.bind("<Enter>", eh[0])
        tab_frame.bind("<Leave>", eh[1])
        tab_frame.bind("<Button-1>", eh[2])
        content.bind("<Button-1>", eh[2])
        icon_lbl.bind("<Button-1>", eh[2])
        title_lbl.bind("<Button-1>", eh[2])
        close_lbl.bind("<Button-1>", eh[3])

        tab_data["frame"] = tab_frame
        tab_data["content"] = content
        tab_data["title_lbl"] = title_lbl
        tab_data["line"] = line
        tab_data["icon_lbl"] = icon_lbl
        tab_data["close_lbl"] = close_lbl

        self._activate_tab(idx)

    def _activate_tab(self, idx: int) -> None:
        if idx >= len(self._tabs):
            return
        old_idx = self._active_tab
        self._active_tab = idx

        if old_idx < len(self._tabs):
            old = self._tabs[old_idx]
            if "frame" in old:
                bg = COLORS["tab_bg"]
                old["frame"].configure(bg=bg)
                old["content"].configure(bg=bg)
                old["title_lbl"].configure(bg=bg, font=self._fonts["tab"])
                old["icon_lbl"].configure(bg=bg)
                old["close_lbl"].configure(bg=bg)
                old["line"].configure(bg=COLORS["divider"])

        new_tab = self._tabs[idx]
        if "frame" in new_tab:
            bg = COLORS["tab_active"]
            new_tab["frame"].configure(bg=bg)
            new_tab["content"].configure(bg=bg)
            new_tab["title_lbl"].configure(bg=bg, font=self._fonts["tab_bold"])
            new_tab["icon_lbl"].configure(bg=bg)
            new_tab["close_lbl"].configure(bg=bg)
            new_tab["line"].configure(bg=COLORS["tab_line"])

        if new_tab["url"]:
            self._url_var.set(new_tab["url"])
        else:
            self._url_var.set("")
        self._update_status_url()

    def _close_tab(self, idx: int) -> None:
        if len(self._tabs) <= 1:
            return
        tab = self._tabs[idx]
        if "frame" in tab:
            tab["frame"].destroy()
        self._tabs.pop(idx)
        if idx <= self._active_tab:
            self._active_tab = max(0, self._active_tab - 1)
        if self._tabs:
            self._activate_tab(self._active_tab)

    def _show_menu(self) -> None:
        menu = tk.Menu(self._parent, tearoff=0, bg=COLORS["bg"], fg=COLORS["txt_primary"],
                       activebackground=COLORS["bg_hover"], activeforeground=COLORS["txt_primary"],
                       bd=0, relief="flat", font=self._fonts["button"])
        menu.add_command(label="🔄 Обновить", command=lambda: self._on_goto())
        menu.add_command(label="📁 Сохранить сессию", command=self._on_save_session)
        menu.add_command(label="📂 Загрузить сессию", command=self._on_load_session)
        menu.add_separator()
        menu.add_command(label="📸 Сделать скриншот", command=self._on_screenshot)
        menu.add_separator()
        menu.add_command(label="⚙ Настройки", command=lambda: None)
        try:
            menu.tk_popup(self._menu_btn.winfo_rootx(), self._menu_btn.winfo_rooty() + 20)
        finally:
            menu.grab_release()

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. Navigation Bar (Omnibox + кнопки как в Chrome)
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_nav_bar(self, parent) -> None:
        nav = tk.Frame(parent, bg=COLORS["surface"], height=48, bd=0, highlightthickness=0)
        nav.pack(fill="x", padx=0, pady=0)
        nav.pack_propagate(False)

        f = self._fonts

        # ── Кнопки навигации ────────────────────────────────────────────────
        btn_frame = tk.Frame(nav, bg=COLORS["surface"], bd=0)
        btn_frame.pack(side="left", padx=(8, 0), pady=4)

        self._back_btn = tk.Label(
            btn_frame, text="◀", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._back_btn.pack(side="left", padx=1)
        self._back_btn.bind("<Button-1>", lambda e: self._log("◀ Назад"))
        self._back_btn.bind("<Enter>", lambda e: self._back_btn.configure(bg=COLORS["bg_hover"]))
        self._back_btn.bind("<Leave>", lambda e: self._back_btn.configure(bg=COLORS["surface"]))

        self._forward_btn = tk.Label(
            btn_frame, text="▶", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._forward_btn.pack(side="left", padx=1)
        self._forward_btn.bind("<Button-1>", lambda e: self._log("▶ Вперёд"))
        self._forward_btn.bind("<Enter>", lambda e: self._forward_btn.configure(bg=COLORS["bg_hover"]))
        self._forward_btn.bind("<Leave>", lambda e: self._forward_btn.configure(bg=COLORS["surface"]))

        self._refresh_btn = tk.Label(
            btn_frame, text="↻", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._refresh_btn.pack(side="left", padx=1)
        self._refresh_btn.bind("<Button-1>", lambda e: self._on_goto())
        self._refresh_btn.bind("<Enter>", lambda e: self._refresh_btn.configure(bg=COLORS["bg_hover"]))
        self._refresh_btn.bind("<Leave>", lambda e: self._refresh_btn.configure(bg=COLORS["surface"]))

        self._home_btn = tk.Label(
            btn_frame, text="🏠", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._home_btn.pack(side="left", padx=1)
        self._home_btn.bind("<Button-1>", lambda e: self._go_home())
        self._home_btn.bind("<Enter>", lambda e: self._home_btn.configure(bg=COLORS["bg_hover"]))
        self._home_btn.bind("<Leave>", lambda e: self._home_btn.configure(bg=COLORS["surface"]))

        # ── Omnibox (Chrome-style URL + search) ────────────────────────────
        omnibox_frame = tk.Frame(nav, bg=COLORS["surface"], bd=0)
        omnibox_frame.pack(side="left", fill="x", expand=True, padx=(6, 0), pady=6)

        # Внешняя рамка (как border-radius в Chrome)
        self._url_border = tk.Frame(
            omnibox_frame, bg=COLORS["omnibox_border"], bd=0, highlightthickness=0,
        )
        self._url_border.pack(fill="x", expand=True, ipadx=0, ipady=0)

        self._url_var = tk.StringVar()
        self._url_entry = tk.Entry(
            self._url_border, textvariable=self._url_var,
            bg=COLORS["omnibox_bg"], fg=COLORS["txt_primary"],
            insertbackground=COLORS["accent"],
            font=f["omnibox"], relief="flat", bd=6,
        )
        self._url_entry.pack(fill="x", expand=True, padx=2, pady=2)
        self._url_entry.bind("<Return>", lambda e: self._on_goto())
        self._url_entry.bind("<FocusIn>", self._on_omnibox_focus)
        self._url_entry.bind("<FocusOut>", self._on_omnibox_blur)

        # Иконки внутри omnibox (слева — замок/страница, справа — закладка)
        self._url_secure_lbl = tk.Label(
            self._url_border, text="🔒", font=f["small"],
            bg=COLORS["omnibox_bg"], fg=COLORS["green"],
        )
        self._url_secure_lbl.place(x=6, y=6)

        # ── Кнопки справа (расширения, профиль) ────────────────────────────
        right_frame = tk.Frame(nav, bg=COLORS["surface"], bd=0)
        right_frame.pack(side="right", padx=(0, 8), pady=4)

        # Закладка (star)
        self._bookmark_star = tk.Label(
            right_frame, text="☆", font=f["tab_bold"], bg=COLORS["surface"],
            fg=COLORS["yellow"], cursor="hand2", padx=6, pady=2,
        )
        self._bookmark_star.pack(side="left", padx=2)
        self._bookmark_star.bind("<Button-1>", lambda e: self._toggle_bookmark())
        self._bookmark_star.bind("<Enter>", lambda e: self._bookmark_star.configure(bg=COLORS["bg_hover"]))
        self._bookmark_star.bind("<Leave>", lambda e: self._bookmark_star.configure(bg=COLORS["surface"]))

        # Расширения (пазл)
        self._extensions_btn = tk.Label(
            right_frame, text="🧩", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["txt_secondary"], cursor="hand2", padx=6, pady=2,
        )
        self._extensions_btn.pack(side="left", padx=2)
        self._extensions_btn.bind("<Button-1>", lambda e: self._log("🧩 Расширения"))
        self._extensions_btn.bind("<Enter>", lambda e: self._extensions_btn.configure(bg=COLORS["bg_hover"]))
        self._extensions_btn.bind("<Leave>", lambda e: self._extensions_btn.configure(bg=COLORS["surface"]))

        # Профиль (аватар)
        self._profile_btn = tk.Label(
            right_frame, text="👤", font=f["tab_bold"], bg=COLORS["surface"],
            fg=COLORS["txt_secondary"], cursor="hand2", padx=6, pady=2,
        )
        self._profile_btn.pack(side="left", padx=2)
        self._profile_btn.bind("<Button-1>", lambda e: self._log("👤 Профиль"))
        self._profile_btn.bind("<Enter>", lambda e: self._profile_btn.configure(bg=COLORS["bg_hover"]))
        self._profile_btn.bind("<Leave>", lambda e: self._profile_btn.configure(bg=COLORS["surface"]))

        # ── Режим работы (маленький переключатель) ─────────────────────────
        mode_frame = tk.Frame(right_frame, bg=COLORS["surface"], bd=0)
        mode_frame.pack(side="right", padx=(6, 0))

        self._mode_var = tk.StringVar(value="headless")
        mode_cb = ttk.Combobox(
            mode_frame, textvariable=self._mode_var, width=8,
            values=["🌐 headless", "👁 visible", "📡 observe"],
            font=f["small"], state="readonly",
        )
        mode_cb.pack(side="left")
        mode_cb.bind("<<ComboboxSelected>>", lambda e: self._log(f"Режим: {self._mode_var.get()}"))

        self._start_btn = tk.Label(
            mode_frame, text="▶", font=f["tab_bold"],
            bg=COLORS["green"], fg=COLORS["txt_white"],
            cursor="hand2", padx=8, pady=2,
        )
        self._start_btn.pack(side="left", padx=(4, 0))
        self._start_btn.bind("<Button-1>", lambda e: self._on_start())
        self._start_btn.bind("<Enter>", lambda e: self._start_btn.configure(bg=COLORS["green"]))
        self._start_btn.bind("<Leave>", lambda e: self._start_btn.configure(bg=COLORS["green"]))

        self._stop_btn = tk.Label(
            mode_frame, text="■", font=f["tab_bold"],
            bg=COLORS["red"], fg=COLORS["txt_white"],
            cursor="hand2", padx=8, pady=2, state="disabled",
        )
        self._stop_btn.pack(side="left", padx=(2, 0))
        self._stop_btn.bind("<Button-1>", lambda e: self._on_stop())

    def _on_omnibox_focus(self, event=None) -> None:
        """Выделить весь текст при фокусе (как в Chrome)."""
        self._url_entry.selection_range(0, "end")
        self._url_border.configure(bg=COLORS["omnibox_focus"])

    def _on_omnibox_blur(self, event=None) -> None:
        """Убрать выделение при потере фокуса."""
        self._url_border.configure(bg=COLORS["omnibox_border"])
        self._update_status_url()

    def _update_status_url(self) -> None:
        """Обновить URL в строке состояния на основе активной вкладки."""
        if self._active_tab < len(self._tabs):
            url = self._tabs[self._active_tab].get("url", "")
            if url:
                self._url_var.set(url)

    def _go_home(self) -> None:
        """Перейти на домашнюю страницу."""
        home = "https://www.google.com"
        self._url_var.set(home)
        self._on_goto()

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. Navigation Bar (Omnibox + кнопки как в Chrome)
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_nav_bar(self, parent) -> None:
        nav = tk.Frame(parent, bg=COLORS["surface"], height=48, bd=0, highlightthickness=0)
        nav.pack(fill="x", padx=0, pady=0)
        nav.pack_propagate(False)

        f = self._fonts

        # ── Кнопки навигации ────────────────────────────────────────────────
        btn_frame = tk.Frame(nav, bg=COLORS["surface"], bd=0)
        btn_frame.pack(side="left", padx=(8, 0), pady=4)

        self._back_btn = tk.Label(
            btn_frame, text="◀", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._back_btn.pack(side="left", padx=1)
        self._back_btn.bind("<Button-1>", lambda e: self._log("◀ Назад"))
        self._back_btn.bind("<Enter>", lambda e: self._back_btn.configure(bg=COLORS["bg_hover"]))
        self._back_btn.bind("<Leave>", lambda e: self._back_btn.configure(bg=COLORS["surface"]))

        self._forward_btn = tk.Label(
            btn_frame, text="▶", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._forward_btn.pack(side="left", padx=1)
        self._forward_btn.bind("<Button-1>", lambda e: self._log("▶ Вперёд"))
        self._forward_btn.bind("<Enter>", lambda e: self._forward_btn.configure(bg=COLORS["bg_hover"]))
        self._forward_btn.bind("<Leave>", lambda e: self._forward_btn.configure(bg=COLORS["surface"]))

        self._refresh_btn = tk.Label(
            btn_frame, text="↻", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._refresh_btn.pack(side="left", padx=1)
        self._refresh_btn.bind("<Button-1>", lambda e: self._on_goto())
        self._refresh_btn.bind("<Enter>", lambda e: self._refresh_btn.configure(bg=COLORS["bg_hover"]))
        self._refresh_btn.bind("<Leave>", lambda e: self._refresh_btn.configure(bg=COLORS["surface"]))

        self._home_btn = tk.Label(
            btn_frame, text="🏠", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._home_btn.pack(side="left", padx=1)
        self._home_btn.bind("<Button-1>", lambda e: self._go_home())
        self._home_btn.bind("<Enter>", lambda e: self._home_btn.configure(bg=COLORS["bg_hover"]))
        self._home_btn.bind("<Leave>", lambda e: self._home_btn.configure(bg=COLORS["surface"]))

        # ── Omnibox (Chrome-style URL + search) ────────────────────────────
        omnibox_frame = tk.Frame(nav, bg=COLORS["surface"], bd=0)
        omnibox_frame.pack(side="left", fill="x", expand=True, padx=(6, 0), pady=6)

        # Внешняя рамка (как border-radius в Chrome)
        self._url_border = tk.Frame(
            omnibox_frame, bg=COLORS["omnibox_border"], bd=0, highlightthickness=0,
        )
        self._url_border.pack(fill="x", expand=True, ipadx=0, ipady=0)

        self._url_var = tk.StringVar()
        self._url_entry = tk.Entry(
            self._url_border, textvariable=self._url_var,
            bg=COLORS["omnibox_bg"], fg=COLORS["txt_primary"],
            insertbackground=COLORS["accent"],
            font=f["omnibox"], relief="flat", bd=6,
        )
        self._url_entry.pack(fill="x", expand=True, padx=2, pady=2)
        self._url_entry.bind("<Return>", lambda e: self._on_goto())
        self._url_entry.bind("<FocusIn>", self._on_omnibox_focus)
        self._url_entry.bind("<FocusOut>", self._on_omnibox_blur)

        # Иконки внутри omnibox (слева — замок/страница, справа — закладка)
        self._url_secure_lbl = tk.Label(
            self._url_border, text="🔒", font=f["small"],
            bg=COLORS["omnibox_bg"], fg=COLORS["green"],
        )
        self._url_secure_lbl.place(x=6, y=6)

        # ── Кнопки справа (расширения, профиль) ────────────────────────────
        right_frame = tk.Frame(nav, bg=COLORS["surface"], bd=0)
        right_frame.pack(side="right", padx=(0, 8), pady=4)

        # Закладка (star)
        self._bookmark_star = tk.Label(
            right_frame, text="☆", font=f["tab_bold"], bg=COLORS["surface"],
            fg=COLORS["yellow"], cursor="hand2", padx=6, pady=2,
        )
        self._bookmark_star.pack(side="left", padx=2)
        self._bookmark_star.bind("<Button-1>", lambda e: self._toggle_bookmark())
        self._bookmark_star.bind("<Enter>", lambda e: self._bookmark_star.configure(bg=COLORS["bg_hover"]))
        self._bookmark_star.bind("<Leave>", lambda e: self._bookmark_star.configure(bg=COLORS["surface"]))

        # Расширения (пазл)
        self._extensions_btn = tk.Label(
            right_frame, text="🧩", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["txt_secondary"], cursor="hand2", padx=6, pady=2,
        )
        self._extensions_btn.pack(side="left", padx=2)
        self._extensions_btn.bind("<Button-1>", lambda e: self._log("🧩 Расширения"))
        self._extensions_btn.bind("<Enter>", lambda e: self._extensions_btn.configure(bg=COLORS["bg_hover"]))
        self._extensions_btn.bind("<Leave>", lambda e: self._extensions_btn.configure(bg=COLORS["surface"]))

        # Профиль (аватар)
        self._profile_btn = tk.Label(
            right_frame, text="👤", font=f["tab_bold"], bg=COLORS["surface"],
            fg=COLORS["txt_secondary"], cursor="hand2", padx=6, pady=2,
        )
        self._profile_btn.pack(side="left", padx=2)
        self._profile_btn.bind("<Button-1>", lambda e: self._log("👤 Профиль"))
        self._profile_btn.bind("<Enter>", lambda e: self._profile_btn.configure(bg=COLORS["bg_hover"]))
        self._profile_btn.bind("<Leave>", lambda e: self._profile_btn.configure(bg=COLORS["surface"]))

        # ── Режим работы (маленький переключатель) ─────────────────────────
        mode_frame = tk.Frame(right_frame, bg=COLORS["surface"], bd=0)
        mode_frame.pack(side="right", padx=(6, 0))

        self._mode_var = tk.StringVar(value="headless")
        mode_cb = ttk.Combobox(
            mode_frame, textvariable=self._mode_var, width=8,
            values=["🌐 headless", "👁 visible", "📡 observe"],
            font=f["small"], state="readonly",
        )
        mode_cb.pack(side="left")
        mode_cb.bind("<<ComboboxSelected>>", lambda e: self._log(f"Режим: {self._mode_var.get()}"))

        self._start_btn = tk.Label(
            mode_frame, text="▶", font=f["tab_bold"],
            bg=COLORS["green"], fg=COLORS["txt_white"],
            cursor="hand2", padx=8, pady=2,
        )
        self._start_btn.pack(side="left", padx=(4, 0))
        self._start_btn.bind("<Button-1>", lambda e: self._on_start())
        self._start_btn.bind("<Enter>", lambda e: self._start_btn.configure(bg=COLORS["green"]))
        self._start_btn.bind("<Leave>", lambda e: self._start_btn.configure(bg=COLORS["green"]))

        self._stop_btn = tk.Label(
            mode_frame, text="■", font=f["tab_bold"],
            bg=COLORS["red"], fg=COLORS["txt_white"],
            cursor="hand2", padx=8, pady=2, state="disabled",
        )
        self._stop_btn.pack(side="left", padx=(2, 0))
        self._stop_btn.bind("<Button-1>", lambda e: self._on_stop())

    def _on_omnibox_focus(self, event=None) -> None:
        """Выделить весь текст при фокусе (как в Chrome)."""
        self._url_entry.selection_range(0, "end")
        self._url_border.configure(bg=COLORS["omnibox_focus"])

    def _on_omnibox_blur(self, event=None) -> None:
        """Убрать выделение при потере фокуса."""
        self._url_border.configure(bg=COLORS["omnibox_border"])
        self._update_status_url()

    def _update_status_url(self) -> None:
        """Обновить URL в строке состояния на основе активной вкладки."""
        if self._active_tab < len(self._tabs):
            url = self._tabs[self._active_tab].get("url", "")
            if url:
                self._url_var.set(url)

    def _go_home(self) -> None:
        """Перейти на домашнюю страницу."""
        home = "https://www.google.com"
        self._url_var.set(home)
        self._on_goto()

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. Navigation Bar (Omnibox + кнопки как в Chrome)
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_nav_bar(self, parent) -> None:
        nav = tk.Frame(parent, bg=COLORS["surface"], height=48, bd=0, highlightthickness=0)
        nav.pack(fill="x", padx=0, pady=0)
        nav.pack_propagate(False)

        f = self._fonts

        # ── Кнопки навигации ────────────────────────────────────────────────
        btn_frame = tk.Frame(nav, bg=COLORS["surface"], bd=0)
        btn_frame.pack(side="left", padx=(8, 0), pady=4)

        self._back_btn = tk.Label(
            btn_frame, text="◀", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._back_btn.pack(side="left", padx=1)
        self._back_btn.bind("<Button-1>", lambda e: self._log("◀ Назад"))
        self._back_btn.bind("<Enter>", lambda e: self._back_btn.configure(bg=COLORS["bg_hover"]))
        self._back_btn.bind("<Leave>", lambda e: self._back_btn.configure(bg=COLORS["surface"]))

        self._forward_btn = tk.Label(
            btn_frame, text="▶", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._forward_btn.pack(side="left", padx=1)
        self._forward_btn.bind("<Button-1>", lambda e: self._log("▶ Вперёд"))
        self._forward_btn.bind("<Enter>", lambda e: self._forward_btn.configure(bg=COLORS["bg_hover"]))
        self._forward_btn.bind("<Leave>", lambda e: self._forward_btn.configure(bg=COLORS["surface"]))

        self._refresh_btn = tk.Label(
            btn_frame, text="↻", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._refresh_btn.pack(side="left", padx=1)
        self._refresh_btn.bind("<Button-1>", lambda e: self._on_goto())
        self._refresh_btn.bind("<Enter>", lambda e: self._refresh_btn.configure(bg=COLORS["bg_hover"]))
        self._refresh_btn.bind("<Leave>", lambda e: self._refresh_btn.configure(bg=COLORS["surface"]))

        self._home_btn = tk.Label(
            btn_frame, text="🏠", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._home_btn.pack(side="left", padx=1)
        self._home_btn.bind("<Button-1>", lambda e: self._go_home())
        self._home_btn.bind("<Enter>", lambda e: self._home_btn.configure(bg=COLORS["bg_hover"]))
        self._home_btn.bind("<Leave>", lambda e: self._home_btn.configure(bg=COLORS["surface"]))

        # ── Omnibox (Chrome-style URL + search) ────────────────────────────
        omnibox_frame = tk.Frame(nav, bg=COLORS["surface"], bd=0)
        omnibox_frame.pack(side="left", fill="x", expand=True, padx=(6, 0), pady=6)

        # Внешняя рамка (как border-radius в Chrome)
        self._url_border = tk.Frame(
            omnibox_frame, bg=COLORS["omnibox_border"], bd=0, highlightthickness=0,
        )
        self._url_border.pack(fill="x", expand=True, ipadx=0, ipady=0)

        self._url_var = tk.StringVar()
        self._url_entry = tk.Entry(
            self._url_border, textvariable=self._url_var,
            bg=COLORS["omnibox_bg"], fg=COLORS["txt_primary"],
            insertbackground=COLORS["accent"],
            font=f["omnibox"], relief="flat", bd=6,
        )
        self._url_entry.pack(fill="x", expand=True, padx=2, pady=2)
        self._url_entry.bind("<Return>", lambda e: self._on_goto())
        self._url_entry.bind("<FocusIn>", self._on_omnibox_focus)
        self._url_entry.bind("<FocusOut>", self._on_omnibox_blur)

        # Иконки внутри omnibox (слева — замок/страница, справа — закладка)
        self._url_secure_lbl = tk.Label(
            self._url_border, text="🔒", font=f["small"],
            bg=COLORS["omnibox_bg"], fg=COLORS["green"],
        )
        self._url_secure_lbl.place(x=6, y=6)

        # ── Кнопки справа (расширения, профиль) ────────────────────────────
        right_frame = tk.Frame(nav, bg=COLORS["surface"], bd=0)
        right_frame.pack(side="right", padx=(0, 8), pady=4)

        # Закладка (star)
        self._bookmark_star = tk.Label(
            right_frame, text="☆", font=f["tab_bold"], bg=COLORS["surface"],
            fg=COLORS["yellow"], cursor="hand2", padx=6, pady=2,
        )
        self._bookmark_star.pack(side="left", padx=2)
        self._bookmark_star.bind("<Button-1>", lambda e: self._toggle_bookmark())
        self._bookmark_star.bind("<Enter>", lambda e: self._bookmark_star.configure(bg=COLORS["bg_hover"]))
        self._bookmark_star.bind("<Leave>", lambda e: self._bookmark_star.configure(bg=COLORS["surface"]))

        # Расширения (пазл)
        self._extensions_btn = tk.Label(
            right_frame, text="🧩", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["txt_secondary"], cursor="hand2", padx=6, pady=2,
        )
        self._extensions_btn.pack(side="left", padx=2)
        self._extensions_btn.bind("<Button-1>", lambda e: self._log("🧩 Расширения"))
        self._extensions_btn.bind("<Enter>", lambda e: self._extensions_btn.configure(bg=COLORS["bg_hover"]))
        self._extensions_btn.bind("<Leave>", lambda e: self._extensions_btn.configure(bg=COLORS["surface"]))

        # Профиль (аватар)
        self._profile_btn = tk.Label(
            right_frame, text="👤", font=f["tab_bold"], bg=COLORS["surface"],
            fg=COLORS["txt_secondary"], cursor="hand2", padx=6, pady=2,
        )
        self._profile_btn.pack(side="left", padx=2)
        self._profile_btn.bind("<Button-1>", lambda e: self._log("👤 Профиль"))
        self._profile_btn.bind("<Enter>", lambda e: self._profile_btn.configure(bg=COLORS["bg_hover"]))
        self._profile_btn.bind("<Leave>", lambda e: self._profile_btn.configure(bg=COLORS["surface"]))

        # ── Режим работы (маленький переключатель) ─────────────────────────
        mode_frame = tk.Frame(right_frame, bg=COLORS["surface"], bd=0)
        mode_frame.pack(side="right", padx=(6, 0))

        self._mode_var = tk.StringVar(value="headless")
        mode_cb = ttk.Combobox(
            mode_frame, textvariable=self._mode_var, width=8,
            values=["🌐 headless", "👁 visible", "📡 observe"],
            font=f["small"], state="readonly",
        )
        mode_cb.pack(side="left")
        mode_cb.bind("<<ComboboxSelected>>", lambda e: self._log(f"Режим: {self._mode_var.get()}"))

        self._start_btn = tk.Label(
            mode_frame, text="▶", font=f["tab_bold"],
            bg=COLORS["green"], fg=COLORS["txt_white"],
            cursor="hand2", padx=8, pady=2,
        )
        self._start_btn.pack(side="left", padx=(4, 0))
        self._start_btn.bind("<Button-1>", lambda e: self._on_start())
        self._start_btn.bind("<Enter>", lambda e: self._start_btn.configure(bg=COLORS["green"]))
        self._start_btn.bind("<Leave>", lambda e: self._start_btn.configure(bg=COLORS["green"]))

        self._stop_btn = tk.Label(
            mode_frame, text="■", font=f["tab_bold"],
            bg=COLORS["red"], fg=COLORS["txt_white"],
            cursor="hand2", padx=8, pady=2, state="disabled",
        )
        self._stop_btn.pack(side="left", padx=(2, 0))
        self._stop_btn.bind("<Button-1>", lambda e: self._on_stop())

    def _on_omnibox_focus(self, event=None) -> None:
        """Выделить весь текст при фокусе (как в Chrome)."""
        self._url_entry.selection_range(0, "end")
        self._url_border.configure(bg=COLORS["omnibox_focus"])

    def _on_omnibox_blur(self, event=None) -> None:
        """Убрать выделение при потере фокуса."""
        self._url_border.configure(bg=COLORS["omnibox_border"])
        self._update_status_url()

    def _update_status_url(self) -> None:
        """Обновить URL в строке состояния на основе активной вкладки."""
        if self._active_tab < len(self._tabs):
            url = self._tabs[self._active_tab].get("url", "")
            if url:
                self._url_var.set(url)

    def _go_home(self) -> None:
        """Перейти на домашнюю страницу."""
        home = "https://www.google.com"
        self._url_var.set(home)
        self._on_goto()

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. Navigation Bar (Omnibox + кнопки как в Chrome)
    # ═══════════════════════════════════════════════════════════════════════════
    def _build_nav_bar(self, parent) -> None:
        nav = tk.Frame(parent, bg=COLORS["surface"], height=48, bd=0, highlightthickness=0)
        nav.pack(fill="x", padx=0, pady=0)
        nav.pack_propagate(False)

        f = self._fonts

        # ── Кнопки навигации ────────────────────────────────────────────────
        btn_frame = tk.Frame(nav, bg=COLORS["surface"], bd=0)
        btn_frame.pack(side="left", padx=(8, 0), pady=4)

        self._back_btn = tk.Label(
            btn_frame, text="◀", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._back_btn.pack(side="left", padx=1)
        self._back_btn.bind("<Button-1>", lambda e: self._log("◀ Назад"))
        self._back_btn.bind("<Enter>", lambda e: self._back_btn.configure(bg=COLORS["bg_hover"]))
        self._back_btn.bind("<Leave>", lambda e: self._back_btn.configure(bg=COLORS["surface"]))

        self._forward_btn = tk.Label(
            btn_frame, text="▶", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._forward_btn.pack(side="left", padx=1)
        self._forward_btn.bind("<Button-1>", lambda e: self._log("▶ Вперёд"))
        self._forward_btn.bind("<Enter>", lambda e: self._forward_btn.configure(bg=COLORS["bg_hover"]))
        self._forward_btn.bind("<Leave>", lambda e: self._forward_btn.configure(bg=COLORS["surface"]))

        self._refresh_btn = tk.Label(
            btn_frame, text="↻", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._refresh_btn.pack(side="left", padx=1)
        self._refresh_btn.bind("<Button-1>", lambda e: self._on_goto())
        self._refresh_btn.bind("<Enter>", lambda e: self._refresh_btn.configure(bg=COLORS["bg_hover"]))
        self._refresh_btn.bind("<Leave>", lambda e: self._refresh_btn.configure(bg=COLORS["surface"]))

        self._home_btn = tk.Label(
            btn_frame, text="🏠", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["btn_icon"], cursor="hand2", padx=6, pady=2,
        )
        self._home_btn.pack(side="left", padx=1)
        self._home_btn.bind("<Button-1>", lambda e: self._go_home())
        self._home_btn.bind("<Enter>", lambda e: self._home_btn.configure(bg=COLORS["bg_hover"]))
        self._home_btn.bind("<Leave>", lambda e: self._home_btn.configure(bg=COLORS["surface"]))

        # ── Omnibox (Chrome-style URL + search) ────────────────────────────
        omnibox_frame = tk.Frame(nav, bg=COLORS["surface"], bd=0)
        omnibox_frame.pack(side="left", fill="x", expand=True, padx=(6, 0), pady=6)

        # Внешняя рамка (как border-radius в Chrome)
        self._url_border = tk.Frame(
            omnibox_frame, bg=COLORS["omnibox_border"], bd=0, highlightthickness=0,
        )
        self._url_border.pack(fill="x", expand=True, ipadx=0, ipady=0)

        self._url_var = tk.StringVar()
        self._url_entry = tk.Entry(
            self._url_border, textvariable=self._url_var,
            bg=COLORS["omnibox_bg"], fg=COLORS["txt_primary"],
            insertbackground=COLORS["accent"],
            font=f["omnibox"], relief="flat", bd=6,
        )
        self._url_entry.pack(fill="x", expand=True, padx=2, pady=2)
        self._url_entry.bind("<Return>", lambda e: self._on_goto())
        self._url_entry.bind("<FocusIn>", self._on_omnibox_focus)
        self._url_entry.bind("<FocusOut>", self._on_omnibox_blur)

        # Иконки внутри omnibox (слева — замок/страница, справа — закладка)
        self._url_secure_lbl = tk.Label(
            self._url_border, text="🔒", font=f["small"],
            bg=COLORS["omnibox_bg"], fg=COLORS["green"],
        )
        self._url_secure_lbl.place(x=6, y=6)

        # ── Кнопки справа (расширения, профиль) ────────────────────────────
        right_frame = tk.Frame(nav, bg=COLORS["surface"], bd=0)
        right_frame.pack(side="right", padx=(0, 8), pady=4)

        # Закладка (star)
        self._bookmark_star = tk.Label(
            right_frame, text="☆", font=f["tab_bold"], bg=COLORS["surface"],
            fg=COLORS["yellow"], cursor="hand2", padx=6, pady=2,
        )
        self._bookmark_star.pack(side="left", padx=2)
        self._bookmark_star.bind("<Button-1>", lambda e: self._toggle_bookmark())
        self._bookmark_star.bind("<Enter>", lambda e: self._bookmark_star.configure(bg=COLORS["bg_hover"]))
        self._bookmark_star.bind("<Leave>", lambda e: self._bookmark_star.configure(bg=COLORS["surface"]))

        # Расширения (пазл)
        self._extensions_btn = tk.Label(
            right_frame, text="🧩", font=f["button"], bg=COLORS["surface"],
            fg=COLORS["txt_secondary"], cursor="hand2", padx=6, pady=2,
        )
        self._extensions_btn.pack(side="left", padx=2)
        self._extensions_btn.bind("<Button-1>", lambda e: self._log("🧩 Расширения"))
        self._extensions_btn.bind("<Enter>", lambda e: self._extensions_btn.configure(bg=COLORS["bg_hover"]))
        self._extensions_btn.bind("<Leave>", lambda e: self._extensions_btn.configure(bg=COLORS["surface"]))

        # Профиль (аватар)
        self._profile_btn = tk.Label(
            right_frame, text="👤", font=f["tab_bold"], bg=COLORS["surface"],
            fg=COLORS["txt_secondary"], cursor="hand2", padx=6, pady=2,
        )
        self._profile_btn.pack(side="left", padx=2)
        self._profile_btn.bind("<Button-1>", lambda e: self._log("👤 Профиль"))
        self._profile_btn.bind("<Enter>", lambda e: self._profile_btn.configure(bg=COLORS["bg_hover"]))
        self._profile_btn.bind("<Leave>", lambda e: self._profile_btn.configure(bg=COLORS["surface"]))

        # ── Режим работы (маленький переключатель) ─────────────────────────
        mode_frame = tk.Frame(right_frame, bg=COLORS["surface"], bd=0)
        mode_frame.pack(side="right", padx=(6, 0))

        self._mode_var = tk.StringVar(value="headless")
        mode_cb = ttk.Combobox(
            mode_frame, textvariable=self._mode_var, width=8,
            values=["🌐 headless", "👁 visible", "📡 observe"],
            font=f["small"], state="readonly",
        )
        mode_cb.pack(side="left")
        mode_cb.bind("<<ComboboxSelected>>", lambda e: self._log(f"Режим: {self._mode_var.get()}"))

        self._start_btn = tk.Label(
            mode_frame, text="▶", font=f["tab_bold"],
            bg=COLORS["green"], fg=COLORS["txt_white"],
            cursor="hand2", padx=8, pady=2,
        )
        self._start_btn.pack(side="left", padx=(4, 0))
        self._start_btn.bind("<Button-1>", lambda e: self._on_start())
        self._start_btn.bind("<Enter>", lambda e: self._start_btn.configure(bg=COLORS["green"]))
        self._start_btn.bind("<Leave>", lambda e: self._start_btn.configure(bg=COLORS["green"]))

        self._stop_btn = tk.Label(
            mode_frame, text="■", font=f["tab_bold"],
            bg=COLORS["red"], fg=COLORS["txt_white"],
            cursor="hand2", padx=8, pady=2, state="disabled",
        )
        self._stop_btn.pack(side="left", padx=(2, 0))
        self._stop_btn.bind("<Button-1>", lambda e: self._on_stop())

    def _on_omnibox_focus(self, event=None) -> None:
        """Выделить весь текст при фокусе (как в Chrome)."""
        self._url_entry.selection_range(0, "end")
        self._url_border.configure(bg=COLORS["omnibox_focus"])

    def _on_omnibox_blur(self, event=None) -> None:
        """Убрать выделение при потере фокуса."""
        self._url_border.configure(bg=COLORS["omnibox_border"])
        self._update_status_url()

    def _update_status_url(self) -> None:
        """Обновить URL в строке состояния на основе активной вкладки."""
        if self._active_tab < len(self._tabs):
            url = self._tabs[self._active_tab].get("url", "")
            if url:
                self._url_var.set(url)

    def _go_home(self) -> None:
        """Перейти на домашнюю страницу."""
        home = "https://www.google.com"
        self._url_var.set(home)
        self._on_goto()
