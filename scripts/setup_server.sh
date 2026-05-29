#!/usr/bin/env bash
# scripts/setup_server.sh — Развёртывание Personal AI на Linux сервере
# Запуск: bash scripts/setup_server.sh
#
# Что делает:
#   1. Создаёт systemd unit для автозапуска
#   2. Устанавливает cron-задачу для ежедневного бэкапа в 03:00
#   3. Создаёт директории logs/ backups/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$(which python3 || which python)"

echo "=== Personal AI — Server Setup ==="
echo "App dir: $APP_DIR"
echo "Python:  $PYTHON"

# ── Create directories ────────────────────────────────────────────────────────
mkdir -p "$APP_DIR/logs" "$APP_DIR/backups"
echo "✅ Directories created"

# ── Systemd service ───────────────────────────────────────────────────────────
SERVICE_FILE="/etc/systemd/system/personal-ai.service"
if [ -d "/etc/systemd/system" ]; then
    sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Personal AI — Autonomous AI Assistant
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$PYTHON $APP_DIR/server_launcher.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable personal-ai
    echo "✅ Systemd service installed: personal-ai.service"
    echo "   Start:  sudo systemctl start personal-ai"
    echo "   Status: sudo systemctl status personal-ai"
    echo "   Logs:   sudo journalctl -u personal-ai -f"
else
    echo "⚠️  systemd not found — skipping service install"
fi

# ── Cron daily backup at 03:00 ────────────────────────────────────────────────
CRON_LINE="0 3 * * * $PYTHON $APP_DIR/scripts/backup.py --dest $APP_DIR/backups >> $APP_DIR/logs/backup.log 2>&1"
# Check if already installed
if crontab -l 2>/dev/null | grep -qF "scripts/backup.py"; then
    echo "✅ Cron backup already installed"
else
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "✅ Cron backup installed (daily at 03:00)"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit $APP_DIR/.env — add your API keys"
echo "  2. sudo systemctl start personal-ai"
echo "  3. python $APP_DIR/main.py --status  # verify"
