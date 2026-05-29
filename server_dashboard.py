# -*- coding: utf-8 -*-
"""
server_dashboard.py — Мониторинг Personal AI на сервере 77.90.2.171

Показывает в реальном времени:
  • Статус сервисов (ai-assistant, bybit-bot)
  • Логи Telegram бота
  • Статус торгового бота
  • Heartbeat сервера

Использование:
  python server_dashboard.py          # Обновление каждые 10 сек
  python server_dashboard.py --logs   # Потоковый вывод логов (tail -f)
  python server_dashboard.py --ssh    # Открыть SSH терминал
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import subprocess
from pathlib import Path

# UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# ── Параметры сервера ─────────────────────────────────────────────────────────

SERVER_HOST = "77.90.2.171"
SERVER_PORT = 22
SERVER_USER = "root"
SERVER_PASS = "cpySlIutZ5Ef0mRsfWXh"

REFRESH_SEC = 10   # интервал обновления дашборда

# ── Аргументы ─────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Personal AI Server Dashboard")
parser.add_argument("--logs",    action="store_true", help="Потоковые логи (tail -f)")
parser.add_argument("--ssh",     action="store_true", help="Открыть SSH терминал")
parser.add_argument("--restart", metavar="SERVICE",   help="Перезапустить сервис (ai-assistant|bybit-bot)")
parser.add_argument("--refresh", type=int, default=REFRESH_SEC, help="Интервал обновления (сек)")
args, _ = parser.parse_known_args()


def _get_ssh():
    """Получить SSH-соединение."""
    try:
        import paramiko
    except ImportError:
        print("Устанавливаю paramiko...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
        import paramiko

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SERVER_HOST, port=SERVER_PORT, username=SERVER_USER,
                password=SERVER_PASS, timeout=10)
    return ssh


def _run(ssh, cmd: str, timeout: int = 15) -> str:
    """Выполнить команду и вернуть вывод."""
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        stdout.channel.settimeout(timeout)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        return out or err
    except Exception as e:
        return f"[ERROR: {e}]"


def _strip_ansi(text: str) -> str:
    """Убрать ANSI escape-коды (цветные логи structlog)."""
    import re
    return re.sub(r'\x1b\[[0-9;]*[mK]|\x1b\[[0-9;]*m|\x1b\[2m|\x1b\[0m', '', text)


def _service_icon(status: str) -> str:
    if "active (running)" in status:
        return "●  RUNNING"
    elif "activating" in status or "auto-restart" in status:
        return "◌  RESTARTING"
    elif "inactive" in status:
        return "○  STOPPED"
    else:
        return "✗  ERROR"


def _clear():
    os.system("cls" if os.name == "nt" else "clear")


def show_dashboard():
    """Основной дашборд — обновляется каждые N секунд."""
    refresh = args.refresh

    while True:
        try:
            ssh = _get_ssh()

            # Собираем данные
            ai_status   = _run(ssh, "systemctl status ai-assistant --no-pager 2>&1 | head -5")
            bot_status  = _run(ssh, "systemctl status bybit-bot --no-pager 2>&1 | head -5")
            heartbeat   = _run(ssh, "cat /opt/ai-assistant/src/data/heartbeat.txt 2>/dev/null")
            ai_log      = _run(ssh, "tail -8 /opt/ai-assistant/logs/service.log 2>/dev/null | grep -v 'getUpdates\\|Conflict\\|polling'")
            bybit_log   = _run(ssh, "tail -6 /opt/bybit-bot/logs/service.log 2>/dev/null")
            disk        = _run(ssh, "df -h / | tail -1 | awk '{print $3\"/\"$2\" (\"$5\" used)\"}'")
            mem         = _run(ssh, "free -m | awk '/Mem:/{print $3\"/\"$2\" MB\"}'")
            load        = _run(ssh, "uptime | awk -F'load average:' '{print $2}'")
            tg_errors   = _run(ssh, "grep -c 'ERROR\\|FAIL\\|Exception' /opt/ai-assistant/logs/service.log 2>/dev/null || echo 0")

            ssh.close()

            # Парсим статус
            ai_icon  = _service_icon(ai_status)
            bot_icon = _service_icon(bot_status)

            # Время работы
            import re
            ai_uptime_m  = re.search(r'(\d+min)', ai_status)
            ai_uptime_h  = re.search(r'(\d+h \d+min)', ai_status)
            ai_uptime_s  = re.search(r'; (\d+s ago)', ai_status)
            ai_uptime    = (ai_uptime_h or ai_uptime_m or ai_uptime_s)
            ai_uptime    = ai_uptime.group(1) if ai_uptime else "?"

            bot_uptime_m = re.search(r'(\d+min)', bot_status)
            bot_uptime_h = re.search(r'(\d+h \d+min)', bot_status)
            bot_uptime_s = re.search(r'; (\d+s ago)', bot_status)
            bot_uptime   = (bot_uptime_h or bot_uptime_m or bot_uptime_s)
            bot_uptime   = bot_uptime.group(1) if bot_uptime else "?"

        except Exception as e:
            _clear()
            print(f"\n  [!] Нет подключения к серверу: {e}")
            print(f"      Повтор через {refresh} сек... (Ctrl+C для выхода)\n")
            time.sleep(refresh)
            continue

        # Отрисовка
        _clear()
        W = 70
        now = time.strftime("%H:%M:%S")

        print("=" * W)
        print(f"  Personal AI — Server Dashboard       {SERVER_HOST}  [{now}]")
        print("=" * W)
        print()

        # Сервисы
        print("  СЕРВИСЫ")
        print(f"  ├─ AI Assistant     {ai_icon:<20}  uptime: {ai_uptime}")
        print(f"  └─ Bybit Bot        {bot_icon:<20}  uptime: {bot_uptime}")
        print()

        # Heartbeat
        if heartbeat and "running" in heartbeat:
            hb_lines = heartbeat.splitlines()
            hb_time  = hb_lines[0].split()[0] + " " + hb_lines[0].split()[1] if len(hb_lines) > 0 else "?"
            hb_agents = hb_lines[1] if len(hb_lines) > 1 else ""
            hb_tg    = hb_lines[2] if len(hb_lines) > 2 else ""
            print(f"  HEARTBEAT:  {hb_time}  |  {hb_agents}  |  {hb_tg}")
        else:
            print("  HEARTBEAT:  [нет данных]")
        print()

        # Ресурсы
        print(f"  РЕСУРСЫ:  RAM {mem}  |  Диск {disk}  |  Load:{load}")
        print()

        # Логи AI
        print("  AI ASSISTANT LOG (последние записи):")
        for line in _strip_ansi(ai_log).splitlines()[-6:]:
            if line.strip():
                # Обрезать длинные строки
                short = line[25:].strip() if len(line) > 25 else line.strip()
                print(f"    {short[:W-6]}")
        print()

        # Логи Bybit
        print("  BYBIT BOT LOG (последние записи):")
        for line in _strip_ansi(bybit_log).splitlines()[-5:]:
            if line.strip():
                short = line.strip()
                # Убрать метку времени structlog
                short = re.sub(r'^\S+Z\s+\[\S+\s*\]\s+', '', short)
                print(f"    {short[:W-6]}")
        print()

        # Ошибки
        try:
            err_count = int(tg_errors.strip())
        except Exception:
            err_count = 0
        err_label = f"  {err_count} ошибок в логе" if err_count > 0 else "  Ошибок нет"
        print(err_label)
        print()
        print("=" * W)
        print(f"  Обновление через {refresh} сек  |  Ctrl+C — выход")
        print(f"  Команды: --logs  --ssh  --restart ai-assistant|bybit-bot")
        print("=" * W)

        time.sleep(refresh)


def stream_logs():
    """Потоковый вывод логов обоих сервисов."""
    print(f"\nПодключаюсь к {SERVER_HOST}...\n")
    try:
        ssh = _get_ssh()
        # tail -f обоих логов через journalctl
        cmd = (
            "tail -n 20 -f /opt/ai-assistant/logs/service.log "
            "/opt/bybit-bot/logs/service.log 2>/dev/null"
        )
        transport = ssh.get_transport()
        channel = transport.open_session()
        channel.exec_command(cmd)

        print(f"==> Логи в реальном времени (Ctrl+C для выхода)\n")
        while True:
            if channel.recv_ready():
                data = channel.recv(4096).decode("utf-8", errors="replace")
                print(_strip_ansi(data), end="", flush=True)
            elif channel.exit_status_ready():
                break
            else:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\nВыход.")
    except Exception as e:
        print(f"\n[!] Ошибка: {e}")


def open_ssh_terminal():
    """Открыть SSH-терминал в новом окне."""
    print(f"\nОткрываю SSH-терминал → {SERVER_USER}@{SERVER_HOST}...\n")

    # Пробуем PuTTY, потом встроенный OpenSSH
    putty = Path(r"C:\Program Files\PuTTY\putty.exe")
    kitty = Path(r"C:\Program Files\KiTTY\kitty.exe")

    if kitty.exists():
        subprocess.Popen([str(kitty), "-ssh", SERVER_HOST, "-l", SERVER_USER,
                          "-pw", SERVER_PASS, "-P", str(SERVER_PORT)])
        print("[OK] KiTTY запущен")
    elif putty.exists():
        subprocess.Popen([str(putty), "-ssh", SERVER_HOST, "-l", SERVER_USER,
                          "-pw", SERVER_PASS, "-P", str(SERVER_PORT)])
        print("[OK] PuTTY запущен")
    else:
        # Windows Terminal / cmd с OpenSSH
        ssh_cmd = f"ssh {SERVER_USER}@{SERVER_HOST} -p {SERVER_PORT}"
        print(f"Команда для подключения:\n  {ssh_cmd}\n")
        print(f"Пароль: {SERVER_PASS}")
        print()
        # Открываем Windows Terminal если есть
        try:
            subprocess.Popen(
                ["wt", "ssh", f"{SERVER_USER}@{SERVER_HOST}", "-p", str(SERVER_PORT)],
                shell=True
            )
            print("[OK] Windows Terminal открыт")
        except Exception:
            # Обычный cmd
            os.system(f'start cmd /k ssh {SERVER_USER}@{SERVER_HOST} -p {SERVER_PORT}')


def restart_service(name: str):
    """Перезапустить сервис на сервере."""
    allowed = {"ai-assistant", "bybit-bot"}
    if name not in allowed:
        print(f"[!] Неизвестный сервис: {name}. Доступны: {allowed}")
        return

    print(f"\nПерезапускаю {name} на сервере...")
    try:
        ssh = _get_ssh()
        result = _run(ssh, f"systemctl restart {name} && sleep 3 && systemctl status {name} --no-pager | head -5")
        ssh.close()
        print(result)
    except Exception as e:
        print(f"[!] Ошибка: {e}")


# ── Точка входа ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if args.ssh:
        open_ssh_terminal()
    elif args.logs:
        stream_logs()
    elif args.restart:
        restart_service(args.restart)
    else:
        try:
            show_dashboard()
        except KeyboardInterrupt:
            print("\n\nВыход из дашборда. Сервер продолжает работать 24/7.")
