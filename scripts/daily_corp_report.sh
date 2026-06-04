#!/bin/bash
# Daily Corporation Report - comprehensive system overview
TOKEN="8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT="1985320458"

# Get trading data
TRADING=$(curl -s http://127.0.0.1:8001/status 2>/dev/null)
BAL=$(echo $TRADING | python3 -c "import sys,json; d=json.load(sys.stdin); print(round(float(d.get('balance_usdt',0)),2))" 2>/dev/null || echo "?")
PNL=$(echo $TRADING | python3 -c "import sys,json; d=json.load(sys.stdin); print(round(float(d.get('daily_pnl',0)),4))" 2>/dev/null || echo "?")
POS=$(echo $TRADING | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('open_positions',d.get('active_positions','?')))" 2>/dev/null || echo "?")

# Get CEO data
CEO=$(curl -s http://127.0.0.1:4000/api/swarm/status 2>/dev/null)
CYCLE=$(echo $CEO | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['ceo'].get('cycle','?'))" 2>/dev/null || echo "?")
ALERTS=$(echo $CEO | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['ceo'].get('alert_count','?'))" 2>/dev/null || echo "?")

# Count active services
SVCS=$(systemctl list-units --type=service --state=active 2>/dev/null | grep -cE 'maxai|bybit|corp|grok|ollama|qdrant|hyperion|panel' || echo "?")

# Build message
MSG="MaxAI Daily Report - $(date '+%d.%m.%Y %H:%M')

Trading (LIVE):
  Balance: \$${BAL} USDT
  PnL today: \$${PNL}
  Open positions: ${POS}

CEO Swarm:
  Cycle: #${CYCLE}
  Active alerts: ${ALERTS}
  Active services: ${SVCS}

Grok Stack:
  Router: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8088/health 2>/dev/null)
  Ollama: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:11434/api/tags 2>/dev/null)

Keys:
  DeepSeek: OK
  Claude: OK
  Groq: auto-refresh daily

Zero-Day Tests:
$(curl -s http://127.0.0.1:4000/api/swarm/zero-day 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); [print('  '+k+': '+v.get('status','?')) for k,v in d.get('tests',{}).items()]" 2>/dev/null)

Panel: http://77.90.2.171
Grok: http://77.90.2.171:3003"

# Send to Telegram
python3 -c "
import urllib.request, json
data = json.dumps({'chat_id': '$CHAT', 'text': '''$MSG'''}).encode()
req = urllib.request.Request('https://api.telegram.org/bot$TOKEN/sendMessage', data=data, headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req, timeout=10) as r:
    d = json.loads(r.read())
    print('Report sent:', d.get('ok'))
"
