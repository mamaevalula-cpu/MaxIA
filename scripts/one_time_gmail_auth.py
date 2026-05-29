#!/usr/bin/env python3
"""one_time_gmail_auth.py v2 ? fixed SO_REUSEADDR, 5 min timeout"""
import json, urllib.parse, urllib.request, urllib.error
import http.server, threading, socketserver, re
from pathlib import Path

ENV_FILE = Path('/root/my_personal_ai/.env')

def load_env():
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, _, v = line.partition('=')
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def save_key(name, value):
    s = ENV_FILE.read_text()
    if (name + '=') in s:
        s = re.sub(rf'^{name}=.*$', f'{name}={value}', s, flags=re.MULTILINE)
    else:
        s = s.rstrip() + '\n' + name + '=' + value + '\n'
    ENV_FILE.write_text(s)
    print(f'  SAVED: {name}', flush=True)

env = load_env()
CLIENT_ID     = env.get('GOOGLE_CLIENT_ID', '')
CLIENT_SECRET = env.get('GOOGLE_CLIENT_SECRET', '')
PORT          = 18080
REDIRECT_URI  = f'http://77.90.2.171:{PORT}'
SCOPE         = 'https://www.googleapis.com/auth/gmail.readonly'

captured_code = [None]
server_done   = threading.Event()

class OAuthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        if 'code' in params:
            captured_code[0] = params['code'][0]
            html = b'<html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#1a1a2e"><h1 style="color:#00d4aa;font-size:48px">&#10003; Authorization successful!</h1><p style="color:#fff;font-size:20px">You can close this tab. MaxAI is now connected to Gmail.</p></body></html>'
            self.wfile.write(html)
            print("\nCode captured!", flush=True)
            server_done.set()
        elif 'error' in params:
            self.wfile.write(f'<h1 style="color:red">Error: {params["error"][0]}</h1>'.encode())
            server_done.set()
        else:
            # Landing page with big button
            auth_params = urllib.parse.urlencode({
                'client_id':     CLIENT_ID,
                'redirect_uri':  REDIRECT_URI,
                'response_type': 'code',
                'scope':         SCOPE,
                'access_type':   'offline',
                'prompt':        'consent',
            })
            auth_link = 'https://accounts.google.com/o/oauth2/v2/auth?' + auth_params
            html = f'''<html><head><meta charset="utf-8"><title>MaxAI Gmail Auth</title></head>
<body style="font-family:sans-serif;text-align:center;padding:80px;background:#0f0f1a">
<h1 style="color:#00d4aa;font-size:36px">MaxAI Gmail Authorization</h1>
<p style="color:#aaa;font-size:18px;margin:20px">Click the button to authorize Gmail access</p>
<a href="{auth_link}" style="display:inline-block;padding:20px 50px;background:#00d4aa;color:#000;font-size:24px;font-weight:bold;border-radius:12px;text-decoration:none;margin-top:20px">
&#128274; Authorize Gmail
</a>
<p style="color:#555;margin-top:40px;font-size:14px">Account: froggyinternet@gmail.com</p>
</body></html>'''.encode()
            self.wfile.write(html)
    def log_message(self, *args): pass

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

def run_server():
    srv = ReusableTCPServer(('0.0.0.0', PORT), OAuthHandler)
    srv.timeout = 1
    print(f'Server listening on port {PORT}', flush=True)
    while not server_done.is_set():
        srv.handle_request()
    srv.server_close()

params = urllib.parse.urlencode({
    'client_id':     CLIENT_ID,
    'redirect_uri':  REDIRECT_URI,
    'response_type': 'code',
    'scope':         SCOPE,
    'access_type':   'offline',
    'prompt':        'consent',
})
auth_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + params

t = threading.Thread(target=run_server, daemon=True)
t.start()

import time; time.sleep(0.5)  # let server start

print('\n' + '='*60, flush=True)
print('GOOGLE OAUTH2 ? READY', flush=True)
print('='*60, flush=True)
print(f'\nRedirect URI to add in Google Console:', flush=True)
print(f'  {REDIRECT_URI}', flush=True)
print(f'\nThen open this URL:', flush=True)
print(f'\n  {auth_url}\n', flush=True)
print('Waiting 5 minutes for authorization...', flush=True)

if server_done.wait(timeout=300):
    code = captured_code[0]
    if code:
        print(f'Exchanging code for tokens...', flush=True)
        data = urllib.parse.urlencode({
            'code':          code,
            'client_id':     CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'redirect_uri':  REDIRECT_URI,
            'grant_type':    'authorization_code',
        }).encode()
        try:
            resp = urllib.request.urlopen('https://oauth2.googleapis.com/token', data=data, timeout=15)
            tokens = json.loads(resp.read())
            if 'refresh_token' in tokens:
                save_key('GOOGLE_REFRESH_TOKEN', tokens['refresh_token'])
                save_key('GOOGLE_ACCESS_TOKEN',  tokens.get('access_token', ''))
                print('\nSUCCESS! Gmail API authorized. GitHub OTP will now work automatically.', flush=True)
            else:
                print(f'No refresh_token: {tokens}', flush=True)
        except urllib.error.HTTPError as e:
            print(f'Token exchange error: {e.read().decode()}', flush=True)
        except Exception as e:
            print(f'Error: {e}', flush=True)
    else:
        print('Access denied.', flush=True)
else:
    print('\nTimeout ? 5 minutes passed without authorization.', flush=True)
