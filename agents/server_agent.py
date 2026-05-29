# -*- coding: utf-8 -*-
"""
agents/server_agent.py — Агент выполнения серверных команд.

Принимает естественный язык → определяет shell-команду через LLM →
выполняет на сервере → возвращает форматированный вывод.

Доступно через:
  - Обычный чат: "покажи логи", "рестарт nginx", "статус сервиса"
  - Telegram: любой текст с серверными ключевыми словами
  - Dashboard /api/chat

Безопасность:
  - Блокирует деструктивные команды (rm -rf /, mkfs, fork bomb)
  - Логирует каждое выполнение
  - Таймаут 60 секунд
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from typing import Optional

from agents.base_agent import AgentInfo, AgentStatus, BaseAgent

log = logging.getLogger("agents.server")

# Рабочая директория по умолчанию
WORKDIR = "/root/my_personal_ai"

# Деструктивные паттерны — всегда блокировать
BLOCKED = [
    r"rm\s+-rf\s+/[^/]",        # rm -rf /root, rm -rf /etc
    r"rm\s+-rf\s+/\s*$",        # rm -rf /
    r"mkfs",                      # форматирование
    r":\(\)\{:\|:&\};:",          # fork bomb
    r"dd\s+if=.*of=/dev/",        # перезапись блочного устройства
    r"> /dev/sd",                  # перезапись диска
    r"chmod\s+777\s+/",            # chmod 777 /
]

# Команды для частых запросов (без LLM, мгновенно)
QUICK_MAP = {
    r"(статус|status)\s*(сервис|service|personal.ai)": "systemctl status personal-ai --no-pager -l",
    r"рестарт|restart\s*(сервис|service)": "systemctl restart personal-ai && sleep 3 && systemctl is-active personal-ai",
    r"стоп|stop\s*(сервис|service)": "systemctl stop personal-ai",
    r"(логи|logs|лог)\s*(сервис|system|system\.log)?$": "tail -50 /root/my_personal_ai/logs/system.log",
    r"логи\s*агент|agents\.log": "tail -50 /root/my_personal_ai/logs/agents.log",
    r"статус\s*nginx|nginx\s*статус": "systemctl status nginx --no-pager && nginx -t 2>&1",
    r"рестарт\s*nginx|nginx\s*рестарт": "nginx -t && systemctl restart nginx && echo OK",
    r"использование\s*(диска|disk)|df\s*-h": "df -h / && du -sh /root/my_personal_ai/data/ /root/my_personal_ai/logs/",
    r"память|memory|ram": "free -h",
    r"процессы|processes|ps\s*aux": "ps aux --sort=-%cpu | head -15",
    r"uptime": "uptime && systemctl is-active personal-ai nginx",
    r"порты|ports|netstat": "ss -tlnp | grep -E '8000|8090|8080|80|22'",
}


def _is_blocked(cmd: str) -> bool:
    for pattern in BLOCKED:
        if re.search(pattern, cmd, re.IGNORECASE):
            return True
    return False


def _quick_lookup(text: str) -> Optional[str]:
    """Быстрая карта частых запросов — без LLM."""
    tl = text.lower().strip()
    for pattern, cmd in QUICK_MAP.items():
        if re.search(pattern, tl, re.IGNORECASE):
            return cmd
    return None


def _run_shell(cmd: str, timeout: int = 60) -> tuple[int, str]:
    """Выполнить shell команду. Возвращает (exit_code, output)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=WORKDIR,
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        combined = out
        if err and err != out:
            combined = (out + "\n[stderr]\n" + err).strip() if out else err
        return r.returncode, combined[:4000] or "(нет вывода)"
    except subprocess.TimeoutExpired:
        return -1, f"⏳ Команда превысила таймаут {timeout}с"
    except Exception as e:
        return -1, f"❌ Ошибка выполнения: {e}"


class ServerAgent(BaseAgent):
    """
    Агент серверного администрирования.
    Переводит запросы на естественном языке в shell команды и выполняет их.
    """

    def __init__(self):
        super().__init__("server")
        self._llm = None
        log.info("ServerAgent initialized")

    def _get_llm(self):
        if self._llm is None:
            try:
                from brain.llm_router import LLMRouter
                self._llm = LLMRouter.get()
            except Exception:
                pass
        return self._llm

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="server",
            description="Выполнение серверных команд и администрирование",
            capabilities=["shell_exec", "service_control", "log_viewer",
                         "process_monitor", "file_ops", "nginx_control"],
        )

    def get_agent_status(self) -> str:
        return "ready"

    def can_handle(self, text: str) -> bool:
        """Проверить, является ли запрос серверной командой."""
        tl = text.lower()
        _kw = (
            "systemctl", "journalctl", "nginx", "рестарт сервис", "restart service",
            "покажи логи", "покажи лог", "show logs", "tail log",
            "статус сервиса", "статус nginx", "логи сервиса",
            "сколько памяти", "использование памяти", "free -h",
            "открытые порты", "netstat", "ss -tln",
            "процессы", "использование cpu", "htop",
            "выполни команду", "запусти команду", "run command",
            "рестарт nginx", "reload nginx", "перезапусти",
            "uptime сервера", "состояние сервера",
            "проверь порт", "проверь сервис", "uptime",
        )
        return any(kw in tl for kw in _kw)

    def process(self, text: str, source: str = "") -> str:
        t0 = time.time()
        log.info("ServerAgent request: %r (source=%s)", text[:80], source)

        # 1. Если пользователь дал явную команду в ``` или после "выполни:"
        direct = self._extract_direct_command(text)
        if direct:
            cmd = direct
            log.info("ServerAgent direct cmd: %r", cmd)
        else:
            # 2. Быстрая карта
            cmd = _quick_lookup(text)
            if not cmd:
                # 3. LLM определяет команду
                cmd = self._ask_llm_for_command(text)
                if not cmd:
                    return "❌ Не удалось определить команду. Попробуй написать явно, например: `выполни: systemctl status nginx`"

        # 4. Проверка безопасности
        if _is_blocked(cmd):
            log.warning("ServerAgent BLOCKED cmd: %r", cmd)
            return f"🚫 Команда заблокирована по соображениям безопасности:\n`{cmd}`"

        # 5. Выполнение
        log.info("ServerAgent executing: %r", cmd)
        exit_code, output = _run_shell(cmd)
        elapsed = round((time.time() - t0) * 1000)

        # 6. Форматирование
        status_icon = "✅" if exit_code == 0 else "⚠️"
        result = (
            f"{status_icon} `{cmd}`\n"
            f"```\n{output}\n```\n"
            f"_exit={exit_code} | {elapsed}ms_"
        )
        return result

    def _extract_direct_command(self, text: str) -> Optional[str]:
        """Извлечь явную команду из текста."""
        # ```bash\ncommand\n``` или `command`
        m = re.search(r'```(?:bash|sh|shell)?\s*\n?(.*?)\n?```', text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
        # "выполни: cmd" / "запусти: cmd" / "run: cmd"
        m = re.search(r'(?:выполни|запусти|run|execute|exec)[:\s]+(.+)', text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None

    def _ask_llm_for_command(self, text: str) -> Optional[str]:
        """Спросить LLM какую команду выполнить."""
        llm = self._get_llm()
        if not llm:
            return None

        prompt = (
            "Ты — Linux-администратор сервера Ubuntu. "
            "Сервер: 77.90.2.171, проект: /root/my_personal_ai, сервис: personal-ai.\n\n"
            f"Запрос пользователя: \"{text}\"\n\n"
            "Ответь ТОЛЬКО одной shell-командой (без пояснений, без markdown).\n"
            "Примеры:\n"
            "- 'покажи логи nginx' → journalctl -u nginx -n 50 --no-pager\n"
            "- 'сколько памяти используется' → free -h\n"
            "- 'статус всех сервисов' → systemctl list-units --type=service --state=running | head -20\n"
            "- 'покажи открытые порты' → ss -tlnp\n"
            "Команда:"
        )

        try:
            resp = llm.ask_simple(prompt, task_type="fast")
            # Убрать лишнее (markdown, пояснения)
            cmd = resp.strip()
            cmd = re.sub(r'^```\w*\s*', '', cmd)
            cmd = re.sub(r'\s*```$', '', cmd)
            cmd = cmd.split('\n')[0].strip()  # только первая строка
            if cmd and len(cmd) > 2:
                return cmd
        except Exception as e:
            log.warning("ServerAgent LLM error: %s", e)
        return None
