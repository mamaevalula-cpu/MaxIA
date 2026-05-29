#!/usr/bin/env python3
"""
MaxAI Gmail IMAP Reader
Uses App Password to read Gmail inbox
Config: /root/my_personal_ai/data/gmail_config.json
"""
import imaplib, email, json, re, time, pathlib
from email.header import decode_header

CONFIG_PATH = pathlib.Path('/root/my_personal_ai/data/gmail_config.json')
CACHE_PATH = pathlib.Path('/root/my_personal_ai/data/gmail_emails_cache.json')

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}

def get_email_text(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body += part.get_payload(decode=True).decode('utf-8', errors='replace')
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode('utf-8', errors='replace')
        except Exception:
            pass
    return body

def fetch_latest_emails(max_emails=20, search_from=None, search_subject=None):
    config = load_config()
    if not config.get('app_password'):
        return {'error': 'Gmail App Password not configured. POST to /api/v1/gmail-setup with {"app_password": "xxxx xxxx xxxx xxxx", "email": "froggyinternet@gmail.com"}'}

    email_addr = config.get('email', 'froggyinternet@gmail.com')
    app_password = config['app_password'].replace(' ', '')

    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com', 993)
        mail.login(email_addr, app_password)
        mail.select('inbox')

        criteria = 'ALL'
        if search_from:
            criteria = f'FROM "{search_from}"'
        elif search_subject:
            criteria = f'SUBJECT "{search_subject}"'

        _, msgs = mail.search(None, criteria)
        msg_ids = msgs[0].split()

        latest_ids = msg_ids[-max_emails:] if len(msg_ids) > max_emails else msg_ids
        latest_ids = list(reversed(latest_ids))

        emails = []
        for mid in latest_ids[:10]:
            _, msg_data = mail.fetch(mid, '(RFC822)')
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject_raw = msg.get('Subject', '')
            subject_parts = decode_header(subject_raw)
            subject = ''.join([
                part.decode(enc or 'utf-8', errors='replace') if isinstance(part, bytes) else part
                for part, enc in subject_parts
            ])

            sender = msg.get('From', '')
            date = msg.get('Date', '')
            body = get_email_text(msg)
            codes = re.findall(r'\b(\d{6})\b', body)

            emails.append({
                'id': mid.decode(),
                'subject': subject,
                'from': sender,
                'date': date,
                'body_preview': body[:500],
                'codes': codes
            })

        mail.close()
        mail.logout()

        result = {'emails': emails, 'total': len(msg_ids), 'ts': time.time()}
        CACHE_PATH.write_text(json.dumps(result, indent=2))
        return result

    except imaplib.IMAP4.error as e:
        return {'error': f'IMAP error: {str(e)}. Check App Password at myaccount.google.com/apppasswords'}
    except Exception as e:
        return {'error': str(e)}

def get_latest_code(service_name):
    result = fetch_latest_emails(search_from=service_name)
    if 'error' in result:
        return result
    for em in result.get('emails', []):
        if service_name.lower() in em['from'].lower() or service_name.lower() in em['subject'].lower():
            if em['codes']:
                return {'code': em['codes'][0], 'subject': em['subject'], 'from': em['from'], 'date': em['date']}
    return {'error': f'No verification email from {service_name} found'}

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        print(json.dumps(get_latest_code(sys.argv[1]), indent=2))
    else:
        print(json.dumps(fetch_latest_emails(), indent=2))
