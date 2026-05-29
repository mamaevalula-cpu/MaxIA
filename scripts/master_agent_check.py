#!/usr/bin/env python3
"""Hourly master agent check - ensures all projects are being worked on"""
import json, time, urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
API = 'http://localhost:8090'

def chat(text, session='master_check'):
    try:
        req = urllib.request.Request(API+'/api/chat',
            data=json.dumps({'text': text, 'session_id': session}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read()).get('response','')[:200]
    except Exception as e: return f'ERROR: {e}'

result = chat('Статус системы: сколько агентов активно, есть ли ошибки? Одна строка.')
print(f'[{time.strftime("%H:%M")}] Master check: {result[:150]}')
