#!/usr/bin/env python3
"""Validate panel HTML before applying - MUST BE RUN BEFORE ANY HTML CHANGE"""
import sys, urllib.request, json, re

def validate(html_path=None):
    """Returns True if panel is working correctly."""
    errors = []
    # 1. HTTP check
    try:
        with urllib.request.urlopen("http://localhost:8090/", timeout=6) as r:
            html = r.read().decode("utf-8")
            if r.status != 200:
                errors.append("HTTP " + str(r.status))
    except Exception as e:
        errors.append("HTTP error: " + str(e))
        return False, errors

    # 2. Inline data check
    if "window.__ST__" not in html:
        errors.append("window.__ST__ missing")
    if "loadDash" not in html:
        errors.append("loadDash missing")
    if "go(" not in html:
        errors.append("go() function missing")

    # 3. Balance check
    m = re.search('"balance_usdt":\s*([\d.]+)', html)
    bal = float(m.group(1)) if m else 0
    if bal < 1:
        errors.append("Balance $0 in panel")

    # 4. Chat API check
    try:
        d = json.dumps({"message": "ping"}).encode()
        with urllib.request.urlopen(
            urllib.request.Request("http://localhost:8090/api/chat", d,
                                   {"Content-Type":"application/json"}), timeout=8) as r:
            resp = json.loads(r.read())
            has_resp = bool(resp.get("response") or resp.get("reply") or resp.get("result"))
            if not has_resp:
                errors.append("Chat returns empty")
    except Exception as e:
        errors.append("Chat error: " + str(e))

    if errors:
        print("VALIDATION FAILED: " + ", ".join(errors))
        return False, errors
    print("VALIDATION PASSED: balance=" + str(bal))
    return True, []

if __name__ == "__main__":
    ok, errs = validate()
    sys.exit(0 if ok else 1)
