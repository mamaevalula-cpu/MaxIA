# MaxAI Capability Packs

🤖 **Корпорация MaxAI** — AI automation services and capability packs.

## Available Packs

| Pack | Description | Price |
|------|-------------|-------|
| Telegram Bot Builder | Professional Telegram bots with commands, DB, API | 5000 RUB / $55 |
| Data Parser | Scrape any website: products, contacts, prices | 3000 RUB / $33 |
| Business Automation | Automate reports, email, Excel, Google Sheets | 4500 RUB / $50 |
| AI Assistant | Integrate ChatGPT/Claude into your business | 8000 RUB / $88 |

## API

```bash
# List packs
curl https://your-server/api/v1/packs

# Order a pack
curl -X POST https://your-server/api/v1/packs/telegram-bot-builder/order \
  -H "Content-Type: application/json" \
  -d '{"contact": "your@email.com", "description": "Need a sales bot"}'
```

## Quick Start (n8n)

Import `n8n_telegram_bot.json` workflow to connect MaxAI to your Telegram bot in 5 minutes.

## Contact

📱 Telegram: @maxai_corp
🌐 Panel: http://77.90.2.171:8090
⚡ Powered by Groq LLaMA 3.3 + MaxAI Server
