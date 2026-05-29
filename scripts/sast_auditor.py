#!/usr/bin/env python3
"""
SAST Security Audit — static analysis of public GitHub repos.
Checks: hardcoded secrets, SQL injection patterns, OWASP Top 10 indicators.
Legal: public repos only, no exploitation, report-only output.
"""
import sys, re, json, time, logging, os
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError

LOG_FILE    = '/root/my_personal_ai/logs/sast_auditor.log'
REPORT_FILE = '/root/my_personal_ai/data/sast_reports.jsonl'

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger('sast_auditor')
log.addHandler(logging.StreamHandler(sys.stdout))

# OWASP-aligned static patterns (informational, not exploiting)
PATTERNS = [
    ('A01_BrokenAccessControl',
     r'role\s*==\s*["\']admin["\']|is_admin\s*=\s*True',
     'high',
     'Возможная проверка роли без серверной авторизации'),
    ('A02_CryptoFailure',
     r'md5\s*\(|sha1\s*\(|DES\.|ECB',
     'high',
     'Устаревший криптографический алгоритм (MD5/SHA1/DES/ECB)'),
    ('A03_SQLInjection',
     r'["\'].*\+.*(?:SELECT|INSERT|UPDATE|DELETE)|execute\s*\(\s*[f"\']',
     'high',
     'Возможная SQL-инъекция — конкатенация в запросе'),
    ('A05_Misconfiguration',
     r'DEBUG\s*=\s*True|SECRET_KEY\s*=\s*["\'][a-z0-9]{1,20}["\']',
     'medium',
     'Debug-режим включён или слабый SECRET_KEY'),
    ('A07_AuthFailure',
     r'password\s*==\s*["\']|token\s*==\s*["\']|verify\s*=\s*False',
     'high',
     'Сравнение пароля/токена в открытом виде или отключена верификация SSL'),
    ('A09_LoggingFailure',
     r'except\s*:\s*pass|except\s+Exception\s*:\s*pass',
     'low',
     'Пустой обработчик исключений скрывает ошибки'),
    ('HardcodedSecret',
     r'(?:api_key|secret|password|token)\s*=\s*["\'][A-Za-z0-9+/]{16,}["\']',
     'high',
     'Возможный захардкоженный секрет/ключ'),
    ('OpenRedirect',
     r'redirect\s*\(\s*request\.|HttpResponseRedirect\s*\(\s*request\.',
     'medium',
     'Возможный Open Redirect через user-controlled input'),
    ('CommandInjection',
     r'os\.system\s*\(|subprocess\.call\s*\(.*shell\s*=\s*True|eval\s*\(',
     'high',
     'Потенциальная инъекция команд ОС или небезопасный eval'),
    ('InsecureRandom',
     r'random\.random\(\)|random\.randint\(',
     'low',
     'Использование небезопасного генератора случайных чисел для security-контекста'),
]

def fetch_github_raw(owner: str, repo: str, path: str) -> str:
    for branch in ('main', 'master'):
        url = f'https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}'
        try:
            req = Request(url, headers={'User-Agent': 'MaxAI-SAST/1.0'})
            with urlopen(req, timeout=10) as r:
                return r.read().decode('utf-8', errors='replace')
        except Exception:
            pass
    return ''

def fetch_repo_tree(owner: str, repo: str) -> list:
    """Get list of Python files in repo (GitHub API, no auth, 60 req/hr limit)."""
    url = f'https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1'
    try:
        req = Request(url, headers={
            'User-Agent': 'MaxAI-SAST/1.0',
            'Accept': 'application/vnd.github.v3+json',
        })
        with urlopen(req, timeout=15) as r:
            tree = json.loads(r.read())
        return [f['path'] for f in tree.get('tree', [])
                if f.get('type') == 'blob' and f['path'].endswith('.py')][:20]
    except Exception as e:
        log.warning('Tree fetch failed %s/%s: %s', owner, repo, e)
        return []

def audit_content(content: str, filename: str) -> list:
    findings = []
    lines = content.split('\n')
    for i, line in enumerate(lines, 1):
        for check_id, pattern, severity, desc in PATTERNS:
            try:
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append({
                        'check': check_id,
                        'severity': severity,
                        'description': desc,
                        'file': filename,
                        'line': i,
                        'snippet': line.strip()[:120],
                    })
            except Exception:
                pass
    return findings

def audit_repo(owner: str, repo: str) -> dict:
    log.info('SAST: %s/%s', owner, repo)
    files = fetch_repo_tree(owner, repo)
    if not files:
        files = ['app.py', 'main.py', 'config.py', 'settings.py', 'utils.py']

    all_findings = []
    files_checked = 0
    for path in files[:15]:
        content = fetch_github_raw(owner, repo, path)
        if content:
            findings = audit_content(content, path)
            all_findings.extend(findings)
            files_checked += 1
        time.sleep(0.3)

    severity_counts = {'high': 0, 'medium': 0, 'low': 0}
    for f in all_findings:
        sev = f.get('severity', 'low')
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    risk_score = min(100,
        severity_counts['high'] * 20 +
        severity_counts['medium'] * 10 +
        severity_counts['low'] * 3)

    report = {
        'repo': f'{owner}/{repo}',
        'files_checked': files_checked,
        'total_files': len(files),
        'findings': all_findings[:20],
        'severity_counts': severity_counts,
        'risk_score': risk_score,
        'ts': time.time(),
        'date': datetime.now().isoformat(),
    }

    with open(REPORT_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(report, ensure_ascii=False) + '\n')

    log.info('  %s/%s — risk_score=%d files=%d findings=%d',
             owner, repo, risk_score, files_checked, len(all_findings))
    return report

def print_report(r: dict):
    print(f"\nSAST REPORT: {r['repo']}")
    print(f"Проверено файлов: {r['files_checked']}/{r['total_files']} "
          f"| Уровень риска: {r['risk_score']}/100")
    sc = r['severity_counts']
    print(f"Находки: [HIGH] {sc['high']} | [MED] {sc['medium']} | [LOW] {sc['low']}")
    for f in r['findings'][:5]:
        print(f"  [{f['severity'].upper()}] {f['file']}:{f['line']} — {f['description']}")
        print(f"    > {f['snippet'][:80]}")

def main():
    targets = [
        ('pallets', 'flask'),
    ]
    if len(sys.argv) >= 3:
        targets = [(sys.argv[1], sys.argv[2])]
    for owner, repo in targets:
        report = audit_repo(owner, repo)
        print_report(report)

if __name__ == '__main__':
    main()
