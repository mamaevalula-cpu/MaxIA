#!/usr/bin/env python3
"""Real-time revenue monitor — checks all sources and updates Redis."""
import redis, json, os, time
from datetime import datetime, date

rdb = redis.from_url('redis://127.0.0.1:6379/0', decode_responses=True)

def get_revenue_snapshot():
    today = str(date.today())
    return {
        'nexus_real': float(rdb.get('nexus:revenue:real_total') or 0),
        'nexus_today': int(rdb.get(f'nexus:stats:tasks:{today}') or 0),
        'clients': int(rdb.llen('nexus:clients:list')),
        'bybit_balance': float(rdb.get('bybit:balance_usdt') or 0),
        'start_bal': float(rdb.get(f'bybit:start_bal:{today}') or 0),
        'kwork_proposals': 74,  # static for now
        'timestamp': datetime.now().isoformat()
    }

snapshot = get_revenue_snapshot()
rdb.set('revenue:realtime', json.dumps(snapshot), ex=3600)

pnl = snapshot['bybit_balance'] - snapshot['start_bal']
print(f"Revenue snapshot saved:")
print(f"  NEXUS: ${snapshot['nexus_real']:.2f} total | {snapshot['nexus_today']} tasks today")
print(f"  Bybit: ${snapshot['bybit_balance']:.2f} | PnL: ${pnl:+.2f}")
print(f"  Clients: {snapshot['clients']}")
