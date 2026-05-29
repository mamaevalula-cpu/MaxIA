from __future__ import annotations
import logging, subprocess, os, re
log = logging.getLogger("agents.code_reviewer")

class CodeReviewerAgent:
    name = "code_reviewer"
    def __init__(self): log.info("CodeReviewerAgent OK")
    def review(self, path: str) -> str:
        if not os.path.exists(path): return f"Not found: {path}"
        issues = []
        r = subprocess.run(["/root/venv/bin/python3","-m","py_compile",path],capture_output=True,text=True)
        if r.returncode != 0: issues.append("SyntaxError: " + r.stderr[:100])
        try:
            code = open(path,encoding="utf-8",errors="replace").read()
            pats = [("password.{0,5}=.{0,5}[chr(39)chr(34)]", "Hardcoded password")]
            for pat,desc in pats:
                if re.search(pat,code,re.IGNORECASE): issues.append("Security: " + desc)
        except Exception: pass
        return os.path.basename(path) + ": " + (chr(10).join(issues) if issues else "OK")
    def process(self, text: str) -> str:
        if ".py" in text: return self.review(text.strip().split()[-1])
        r = subprocess.run(["find","/root/my_personal_ai","-name","*.py","-newer","/root/my_personal_ai/.env","-not","-path","*pycache*"],capture_output=True,text=True)
        files = r.stdout.splitlines()[:5]
        return chr(10).join(self.review(f) for f in files) if files else "No recent changes"
