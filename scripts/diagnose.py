#!/usr/bin/env python3
import sys, os, subprocess
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')
from datetime import datetime

def sh(cmd, t=5):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
        return (res.stdout.strip() or res.stderr.strip())[:300]
    except Exception as e:
        return f'ERR:{e}'

def main():
    out = []
    out.append(f"=== DIAG {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    svc  = sh("systemctl is-active personal-ai.service")
    rsts = sh("systemctl show personal-ai.service --property=NRestarts --value")
    pid  = sh("cat /root/my_personal_ai/data/daemon.pid 2>/dev/null")
    tglk = sh("cat /tmp/personal_ai_telegram.lock 2>/dev/null")
    mem  = sh("free -m | awk 'NR==2{printf \"used=%sMB free=%sMB\",$3,$4}'")
    out.append(f"[SVC] {svc} restarts={rsts} pid={pid} tglock={tglk}")
    out.append(f"[MEM] {mem}")
    try:
        from dotenv import dotenv_values
        env = dotenv_values('/root/my_personal_ai/.env')
        keys = []
        for k in ['DEEPSEEK_API_KEY','GROQ_API_KEY','OPENROUTER_API_KEY','CEREBRAS_API_KEY','TOGETHER_API_KEY']:
            keys.append(f"{k.split('_')[0]}={'OK' if env.get(k) else 'MISS'}")
        out.append(f"[KEYS] {' '.join(keys)}")
    except:
        pass
    errs  = sh("tail -50 /root/my_personal_ai/logs/errors.log 2>/dev/null | grep -v SOCKS | tail -4")
    # LLM info is in service.log
    brain = sh("grep 'LLM:' /root/my_personal_ai/logs/service.log 2>/dev/null | tail -5")
    tq    = sh("tail -10 /root/my_personal_ai/logs/task_queue.log 2>/dev/null | tail -4")
    tg    = sh(r"grep 'MSG uid\|telegram.*bot\|polling' /root/my_personal_ai/logs/agents.log 2>/dev/null | tail -3")
    slog  = sh("tail -6 /root/my_personal_ai/logs/service.log 2>/dev/null")
    out.append(f"[ERRORS]\n{errs or 'none'}")
    out.append(f"[LLM_RECENT]\n{brain or 'no LLM calls yet'}")
    out.append(f"[TASKS]\n{tq or 'no task log'}")
    out.append(f"[TG]\n{tg or 'no tg entries'}")
    out.append(f"[SVC_LOG]\n{slog or 'empty'}")
    try:
        import httpx
        from dotenv import dotenv_values as dv
        e = dv('/root/my_personal_ai/.env')
        k = e.get('DEEPSEEK_API_KEY','')
        if k:
            resp = httpx.post('https://api.deepseek.com/chat/completions',
                headers={'Authorization': f'Bearer {k}'},
                json={'model':'deepseek-chat','messages':[{'role':'user','content':'1'}],'max_tokens':2},
                timeout=7)
            out.append(f"[API] DeepSeek={resp.status_code}")
        else:
            out.append("[API] DeepSeek=NO_KEY")
    except Exception as e2:
        out.append(f"[API] DeepSeek=ERR({str(e2)[:40]})")
    print("\n".join(out))

if __name__ == '__main__':
    main()
