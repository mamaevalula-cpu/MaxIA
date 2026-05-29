#!/usr/bin/env python3
"""Balance monitor cron script"""
import sys, os, json
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')
from dotenv import load_dotenv
load_dotenv()

try:
    from core.balance_monitor import get_all_balances, save_report
    balances = get_all_balances()
    path = save_report()
    print('Balance report saved:', path)
    print(json.dumps(balances, indent=2, ensure_ascii=False)[:500])
except Exception as e:
    print('Balance monitor error:', str(e))
    import traceback; traceback.print_exc()
