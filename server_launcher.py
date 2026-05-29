#!/usr/bin/env python3
"""
server_launcher.py — Запуск системы для 24/7 работы на сервере.

Функции:
- Автоматический перезапуск при падении
- Graceful shutdown
- Health monitoring
- Логирование
- PID management
"""

import os
import sys
import signal
import subprocess
import time
import logging
from pathlib import Path
from typing import Optional

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/server_launcher.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


class ServerLauncher:
    """Launcher для 24/7 работы."""

    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.pid_file = self.base_dir / "logs" / "server.pid"
        self.process: Optional[subprocess.Popen] = None
        self.restart_count = 0
        self.max_restarts = 5
        self.restart_cooldown = 10  # секунды
        self.running = True
        self._last_backup_day: int = -1  # для ежедневного бэкапа

    def start(self):
        """Запуск системы."""
        log.info("=" * 60)
        log.info("Starting Personal AI Server (24/7 mode)")
        log.info("=" * 60)

        # Обработчики сигналов
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Сохранение PID процесса launcher
        self.pid_file.parent.mkdir(exist_ok=True)
        with open(self.pid_file, 'w') as f:
            f.write(str(os.getpid()))

        log.info("Server PID: %d", os.getpid())

        # Основной цикл
        while self.running:
            try:
                self._run_app()
            except Exception as e:
                log.error("Unexpected error in launcher: %s", e)

            if self.running:  # Если не shutdown
                self._maybe_run_backup()
                self._handle_restart()

        self._cleanup()

    def _run_app(self):
        """Запуск приложения."""
        try:
            # Команда для запуска
            cmd = [
                sys.executable,
                str(self.base_dir / "main.py"),
                "--no-gui",
                "--no-telegram"  # Telegram уже запущен на сервере или не нужен
            ]

            log.info("Starting application: %s", ' '.join(cmd))
            self.process = subprocess.Popen(
                cmd,
                cwd=str(self.base_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            # Ожидание окончания процесса
            stdout, stderr = self.process.communicate(timeout=None)

            if self.process.returncode == 0:
                log.info("Application exited cleanly")
            else:
                log.error("Application exited with code %d", self.process.returncode)
                if stderr:
                    log.error("STDERR: %s", stderr[-500:])  # Последние 500 символов

        except subprocess.TimeoutExpired:
            log.warning("Application timeout")
            self.process.kill()
        except Exception as e:
            log.error("Failed to run application: %s", e)

    def _handle_restart(self):
        """Обработка перезапуска."""
        if not self.running:
            return

        self.restart_count += 1

        if self.restart_count > self.max_restarts:
            log.error("Max restarts exceeded (%d), stopping", self.max_restarts)
            self.running = False
            return

        log.warning("Restarting application (attempt %d/%d)", self.restart_count, self.max_restarts)
        log.info("Waiting %d seconds before restart...", self.restart_cooldown)
        time.sleep(self.restart_cooldown)

    def _signal_handler(self, signum, frame):
        """Обработка сигналов."""
        log.info("Received signal %d, initiating graceful shutdown", signum)
        self.running = False

        if self.process:
            log.info("Terminating application process")
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                log.warning("Force killing application process")
                self.process.kill()

    def _maybe_run_backup(self) -> None:
        """Run daily backup if it hasn't been done today."""
        import datetime as _dt
        today = _dt.date.today().toordinal()
        if today == self._last_backup_day:
            return
        self._last_backup_day = today
        log.info("Running scheduled daily backup...")
        try:
            from scripts.backup import scheduled_backup_hook
            scheduled_backup_hook()
        except Exception as e:
            log.error("Daily backup failed: %s", e)

    def _cleanup(self):
        """Очистка при выходе."""
        log.info("Cleaning up...")
        if self.pid_file.exists():
            self.pid_file.unlink()
        log.info("Server stopped. Total restarts: %d", self.restart_count)


if __name__ == "__main__":
    launcher = ServerLauncher()
    launcher.start()