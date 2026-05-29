# MaxAI Telegram Bot Deploy Action

Deploy a MaxAI-powered Telegram bot to your server in **one GitHub Action step**.

## What it does

1. Connects to your VPS via SSH
2. Installs dependencies
3. Deploys the bot as a background process
4. Your bot is live in ~30 seconds

## Usage

```yaml
- uses: maxai-corp/maxai-telegram-action@v1
  with:
    bot_token: ${{ secrets.BOT_TOKEN }}
    server_host: ${{ secrets.SERVER_HOST }}
    server_key: ${{ secrets.SERVER_SSH_KEY }}
```

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `bot_token` | ✅ | Telegram bot token from @BotFather |
| `server_host` | ✅ | Your VPS IP or domain |
| `server_key` | ✅ | SSH private key (base64 encoded) |
| `maxai_api_url` | ❌ | MaxAI API URL (default: MaxAI Cloud) |
| `chat_id` | ❌ | Telegram chat for deploy notifications |

## Full workflow example

```yaml
name: Deploy Telegram Bot
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: maxai-corp/maxai-telegram-action@v1
        with:
          bot_token: ${{ secrets.BOT_TOKEN }}
          server_host: ${{ secrets.SERVER_HOST }}
          server_key: ${{ secrets.SERVER_SSH_KEY }}
          chat_id: ${{ secrets.TELEGRAM_CHAT_ID }}
```

## Custom bot / need more features?

→ Contact **@maxai_corp** on Telegram
→ Custom Telegram bot from **$33** / **3000 RUB**
→ Full automation service: parsers, CRM integration, AI workflows

## Powered by

**MaxAI Corporation** — AI automation 24/7
API: http://77.90.2.171:8090
Telegram: @maxai_corp
