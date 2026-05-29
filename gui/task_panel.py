# -*- coding: utf-8 -*-
"""
gui/task_panel.py — Live task tracking panel.

Отображает список агентских задач в реальном времени:
  • Поле ввода задачи + кнопка Run
  • Список задач с цветовыми статусами (pending/running/done/failed)
  • Live лог шагов выбранной задачи
  • Кнопка отмены для running задач

Монтируется в main_window.py как вкладка "🤖 Агент".
"""

from __future__ import annotations

import asyncio
import threading
import tkinter as tk
from tkinter import scrolledtext
from typing import Optional

_CTK_OK = False
try:
    import customtkinter as ctk
    _CTK_OK = True
except ImportError:
    pass


class TaskPanel:
    """
    Task execution panel.
    parent: a Frame/CTkFrame from the main window.
    loop:   the asyncio event loop running in the background thread.
    """

    COLORS = {
        "pending":   "#888888",
        "running":   "#3b8bfa",
        "done":      "#2ecc71",
        "failed":    "#e74c3c",
        "cancelled": "#e67e22",
    }

    def __init__(self, parent, loop: asyncio.AbstractEventLoop) -> None:
        self._parent = parent
        self._loop   = loop
        self._selected_task_id: Optional[str] = None
        self._task_widgets: dict = {}

        self._build()

        # Poll for task list updates
        self._poll_tasks()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        p = self._parent

        if _CTK_OK:
            self._build_ctk(p)
        else:
            self._build_tk(p)

    def _build_ctk(self, p) -> None:
        # ── Top: input bar ────────────────────────────────────────────────────
        top = ctk.CTkFrame(p, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 4))

        ctk.CTkLabel(top, text="Задача:", width=60).pack(side="left", padx=(0, 4))
        self._entry = ctk.CTkEntry(top, placeholder_text="Опиши задачу для агента…")
        self._entry.pack(side="left", fill="x", expand=True, padx=4)
        self._entry.bind("<Return>", lambda _: self._submit())

        self._run_btn = ctk.CTkButton(top, text="▶ Run", width=80, command=self._submit)
        self._run_btn.pack(side="left", padx=(4, 0))

        # ── Middle: task list (left) + step log (right) ────────────────────
        mid = ctk.CTkFrame(p, fg_color="transparent")
        mid.pack(fill="both", expand=True, padx=10, pady=4)
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=2)
        mid.rowconfigure(0, weight=1)

        # Task list
        left = ctk.CTkFrame(mid, fg_color="#1e1e2e")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        ctk.CTkLabel(left, text="Задачи", font=("", 12, "bold")).pack(pady=(6, 2))
        self._task_list_frame = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self._task_list_frame.pack(fill="both", expand=True, padx=4, pady=4)

        # Step log
        right = ctk.CTkFrame(mid, fg_color="#1e1e2e")
        right.grid(row=0, column=1, sticky="nsew")

        ctk.CTkLabel(right, text="Шаги", font=("", 12, "bold")).pack(pady=(6, 2))
        self._log = scrolledtext.ScrolledText(
            right, wrap=tk.WORD, state=tk.DISABLED,
            bg="#181825", fg="#cdd6f4", font=("Consolas", 9),
            relief="flat", borderwidth=0,
        )
        self._log.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        # ── Bottom: cancel button ─────────────────────────────────────────────
        bot = ctk.CTkFrame(p, fg_color="transparent")
        bot.pack(fill="x", padx=10, pady=(0, 8))
        self._cancel_btn = ctk.CTkButton(
            bot, text="⛔ Отмена", width=100, fg_color="#c0392b",
            state="disabled", command=self._cancel
        )
        self._cancel_btn.pack(side="right")

        self._status_label = ctk.CTkLabel(bot, text="Готов", text_color="#888")
        self._status_label.pack(side="left")

    def _build_tk(self, p) -> None:
        # Fallback plain Tk
        top = tk.Frame(p, bg="#1e1e2e")
        top.pack(fill="x", padx=8, pady=6)

        tk.Label(top, text="Задача:", bg="#1e1e2e", fg="white").pack(side="left")
        self._entry = tk.Entry(top, bg="#313244", fg="white", insertbackground="white")
        self._entry.pack(side="left", fill="x", expand=True, padx=4)
        self._entry.bind("<Return>", lambda _: self._submit())

        self._run_btn = tk.Button(top, text="▶ Run", command=self._submit,
                                  bg="#3b8bfa", fg="white")
        self._run_btn.pack(side="left")

        panes = tk.PanedWindow(p, orient=tk.HORIZONTAL, bg="#1e1e2e", sashwidth=4)
        panes.pack(fill="both", expand=True, padx=8, pady=4)

        left = tk.Frame(panes, bg="#1e1e2e")
        panes.add(left, width=200)
        tk.Label(left, text="Задачи", bg="#1e1e2e", fg="white",
                 font=("", 11, "bold")).pack()
        self._task_listbox = tk.Listbox(left, bg="#181825", fg="#cdd6f4",
                                         selectbackground="#3b8bfa")
        self._task_listbox.pack(fill="both", expand=True)
        self._task_listbox.bind("<<ListboxSelect>>", self._on_select_listbox)

        right = tk.Frame(panes, bg="#1e1e2e")
        panes.add(right)
        self._log = scrolledtext.ScrolledText(
            right, wrap=tk.WORD, state=tk.DISABLED,
            bg="#181825", fg="#cdd6f4", font=("Consolas", 9)
        )
        self._log.pack(fill="both", expand=True)

        bot = tk.Frame(p, bg="#1e1e2e")
        bot.pack(fill="x", padx=8, pady=4)
        self._cancel_btn = tk.Button(bot, text="⛔ Отмена", command=self._cancel,
                                      bg="#c0392b", fg="white", state="disabled")
        self._cancel_btn.pack(side="right")
        self._status_label = tk.Label(bot, text="Готов", bg="#1e1e2e", fg="#888")
        self._status_label.pack(side="left")

        self._task_listbox_ids: list = []

    # ── Submit ────────────────────────────────────────────────────────────────

    def _submit(self) -> None:
        task_text = self._entry.get().strip()
        if not task_text:
            return

        self._entry.delete(0, "end")
        self._set_status("Запуск…")

        def _run_in_bg() -> None:
            try:
                from agents.task_executor_agent import TaskExecutorAgent, ProgressEvent

                agent = TaskExecutorAgent.get()

                def on_progress(evt: ProgressEvent) -> None:
                    self._parent.after(0, lambda: self._append_log(evt))

                future = asyncio.run_coroutine_threadsafe(
                    agent.submit(task_text, on_progress=on_progress),
                    self._loop,
                )
                task_id = future.result(timeout=10)
                self._parent.after(0, lambda: self._set_status(f"Выполняется [{task_id}]"))
            except Exception as e:
                self._parent.after(0, lambda: self._set_status(f"Ошибка: {e}"))

        threading.Thread(target=_run_in_bg, daemon=True).start()

    # ── Cancel ────────────────────────────────────────────────────────────────

    def _cancel(self) -> None:
        if self._selected_task_id is None:
            return
        try:
            from agents.task_executor_agent import TaskExecutorAgent
            ok = TaskExecutorAgent.get().cancel_task(self._selected_task_id)
            if ok:
                self._set_status(f"Отменено [{self._selected_task_id}]")
        except Exception as e:
            self._set_status(f"Cancel error: {e}")

    # ── Log append ────────────────────────────────────────────────────────────

    def _append_log(self, evt) -> None:
        self._log.config(state=tk.NORMAL)
        icon = "✅" if evt.is_final else "⚙"
        tool = evt.tool_name or "think"
        line = f"[{evt.step_num}] {icon} {tool}: {evt.observation[:200]}\n"
        self._log.insert(tk.END, line)
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)

        if evt.is_final:
            self._set_status(f"Готово [{evt.task_id}]")
            self._cancel_btn.configure(state="disabled")

    # ── Poll task list ────────────────────────────────────────────────────────

    def _poll_tasks(self) -> None:
        try:
            from agents.task_executor_agent import TaskExecutorAgent
            tasks = TaskExecutorAgent.get().list_tasks()
            self._refresh_task_list(tasks)
        except Exception:
            pass
        self._parent.after(2000, self._poll_tasks)

    def _refresh_task_list(self, tasks: list) -> None:
        if not _CTK_OK:
            self._refresh_task_list_tk(tasks)
            return

        # Rebuild CTk task list
        for w in self._task_list_frame.winfo_children():
            w.destroy()
        self._task_widgets.clear()

        for t in tasks[:20]:
            color = self.COLORS.get(t["status"], "#888")
            row = ctk.CTkFrame(self._task_list_frame, fg_color="#313244", corner_radius=4)
            row.pack(fill="x", pady=2, padx=2)

            dot = ctk.CTkLabel(row, text="●", text_color=color, width=18)
            dot.pack(side="left", padx=(4, 0))

            label_text = f"{t['task'][:40]}…" if len(t["task"]) > 40 else t["task"]
            lbl = ctk.CTkLabel(row, text=label_text, anchor="w", font=("", 10))
            lbl.pack(side="left", fill="x", expand=True, padx=4)

            steps_lbl = ctk.CTkLabel(row, text=f"{t['steps']}st {t['elapsed']}",
                                      text_color="#888", font=("", 9))
            steps_lbl.pack(side="right", padx=4)

            tid = t["task_id"]
            for widget in (row, dot, lbl, steps_lbl):
                widget.bind("<Button-1>", lambda _, tid=tid: self._select_task(tid))

            self._task_widgets[tid] = row

    def _refresh_task_list_tk(self, tasks: list) -> None:
        if not hasattr(self, "_task_listbox"):
            return
        self._task_listbox.delete(0, tk.END)
        self._task_listbox_ids = []
        for t in tasks[:20]:
            label = f"[{t['status'][:4]}] {t['task'][:35]}"
            self._task_listbox.insert(tk.END, label)
            self._task_listbox_ids.append(t["task_id"])

    def _on_select_listbox(self, event) -> None:
        sel = self._task_listbox.curselection()
        if sel and hasattr(self, "_task_listbox_ids"):
            idx = sel[0]
            if idx < len(self._task_listbox_ids):
                self._select_task(self._task_listbox_ids[idx])

    def _select_task(self, task_id: str) -> None:
        self._selected_task_id = task_id
        self._load_task_log(task_id)

        try:
            from agents.task_executor_agent import TaskExecutorAgent, TaskStatus
            record = TaskExecutorAgent.get().get_task(task_id)
            if record and record.status == TaskStatus.RUNNING:
                self._cancel_btn.configure(state="normal")
            else:
                self._cancel_btn.configure(state="disabled")
        except Exception:
            pass

    def _load_task_log(self, task_id: str) -> None:
        try:
            from agents.task_executor_agent import TaskExecutorAgent
            record = TaskExecutorAgent.get().get_task(task_id)
            if record is None:
                return

            self._log.config(state=tk.NORMAL)
            self._log.delete("1.0", tk.END)
            self._log.insert(tk.END, f"Task: {record.task}\n{'─'*50}\n")

            for sr in record.steps:
                icon = "✅" if sr.is_final else "⚙"
                tool = sr.tool_call.name if sr.tool_call else "think"
                self._log.insert(tk.END,
                    f"[{sr.step}] {icon} {tool} ({sr.elapsed_ms:.0f}ms):\n  {sr.observation[:200]}\n")

            if record.result and record.result.ok:
                self._log.insert(tk.END, f"\n✅ Answer:\n{record.result.answer[:500]}\n")
            elif record.error:
                self._log.insert(tk.END, f"\n❌ Error: {record.error}\n")

            self._log.see(tk.END)
            self._log.config(state=tk.DISABLED)
        except Exception as e:
            pass

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, text: str) -> None:
        try:
            self._status_label.configure(text=text)
        except Exception:
            pass
