#!/bin/bash
# Gmail App Password Setup Script
# Usage: bash /root/my_personal_ai/scripts/setup_gmail.sh <app_password>

if [ -z "$1" ]; then
    echo "Gmail App Password Setup"
    echo "========================"
    echo ""
    echo "Steps to get App Password:"
    echo "1. Go to: https://myaccount.google.com/security"
    echo "2. Enable 2-Step Verification (required)"
    echo "3. Go to: https://myaccount.google.com/apppasswords"
    echo "4. App name: 'AI Server' -> Generate"
    echo "5. Copy the 16-character password"
    echo ""
    echo "Then run:"
    echo "  bash /root/my_personal_ai/scripts/setup_gmail.sh xxxx-xxxx-xxxx-xxxx"
    exit 1
fi

APP_PASS=$(echo "$1" | tr -d ' -')
echo "Setting App Password (${#APP_PASS} chars)..."

# Update .env file
cd /root/my_personal_ai
sed -i "s/^EMAIL_PASSWORD=.*/EMAIL_PASSWORD=${APP_PASS}/" .env
echo "Updated .env"

# Test connection
python3 -c "
import imaplib, os
from dotenv import load_dotenv
load_dotenv()
addr = os.getenv('EMAIL_ADDRESS')
pwd = os.getenv('EMAIL_PASSWORD')
try:
    m = imaplib.IMAP4_SSL('imap.gmail.com', 993)
    m.login(addr, pwd)
    m.logout()
    print(f'SUCCESS: Connected as {addr}')
except Exception as e:
    print(f'FAILED: {e}')
"

# Restart service to pick up new credentials
systemctl restart personal-ai
sleep 3
systemctl status personal-ai --no-pager | head -4
echo "Done. Email agent should now connect."
