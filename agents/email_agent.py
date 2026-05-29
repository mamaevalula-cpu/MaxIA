#!/usr/bin/env python3
"""
EmailAgent - Gmail IMAP reader and AI key extractor for MaxAI.
Reads Gmail inbox, extracts API keys, supports search and reply.
"""
import logging, imaplib, email, re, os, time
from email.header import decode_header
from typing import List, Dict, Any, Optional
from agents.base_agent import BaseAgent, AgentInfo

log = logging.getLogger("agents.email")


class EmailAgent(BaseAgent):
    """Gmail email reader with API key extraction."""

    def __init__(self):
        super().__init__("email")
        self._address = os.getenv("EMAIL_ADDRESS", "")
        self._password = os.getenv("EMAIL_PASSWORD", "")
        self._imap_server = os.getenv("IMAP_SERVER", "imap.gmail.com")
        self._imap_port = int(os.getenv("IMAP_PORT", "993"))
        # Second mailbox (DeepSeek/Bybit email)
        self._address2 = os.getenv("EMAIL2_ADDRESS", "")
        self._password2 = os.getenv("EMAIL2_APP_PASSWORD", os.getenv("EMAIL2_PASSWORD", ""))
        self._mail2 = None
        self._connected = False
        self._mail = None
        self._inbox_cache: List[Dict] = []
        self._last_fetch = 0

    def can_handle(self, text: str) -> bool:
        kw = ["почта", "email", "письм", "inbox", "gmail", "прочитай письм",
              "новые письма", "ключ из почты", "api key из почты"]
        return any(k in text.lower() for k in kw)

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="email",
            description="Gmail reader: reads inbox, extracts API keys, searches emails.",
            capabilities=["read_inbox", "search_email", "extract_api_keys", "email_status"],
            version="1.0.0",
        )

    def _connect(self) -> bool:
        """Connect to Gmail IMAP."""
        if not self._address or not self._password:
            log.warning("EmailAgent: no credentials set")
            return False
        try:
            mail = imaplib.IMAP4_SSL(self._imap_server, self._imap_port)
            mail.login(self._address, self._password)
            # Note: Gmail requires App Password (not regular password)
            # Generate at: https://myaccount.google.com/apppasswords
            # Set EMAIL_PASSWORD=<16-char-app-password> in .env
            self._mail = mail
            self._connected = True
            log.info("EmailAgent: connected to %s as %s", self._imap_server, self._address)
            return True
        except imaplib.IMAP4.error as e:
            log.error("EmailAgent: IMAP login failed: %s", e)
            self._connected = False
            import time; self._last_connect_fail = time.time()
            return False
        except Exception as e:
            log.error("EmailAgent: connection error: %s", e)
            self._connected = False
            import time; self._last_connect_fail = time.time()
            return False

    def _ensure_connected(self) -> bool:
        # Cooldown: don't retry too frequently if last attempt failed
        if hasattr(self, '_last_connect_fail') and self._last_connect_fail:
            import time
            if time.time() - self._last_connect_fail < 300:  # 5 min cooldown
                return False
        if self._connected and self._mail:
            try:
                self._mail.noop()
                return True
            except Exception:
                self._connected = False
        return self._connect()

    def _decode_header(self, value: str) -> str:
        parts = decode_header(value)
        result = []
        for data, charset in parts:
            if isinstance(data, bytes):
                try:
                    result.append(data.decode(charset or 'utf-8', errors='replace'))
                except Exception:
                    result.append(data.decode('utf-8', errors='replace'))
            else:
                result.append(str(data))
        return ''.join(result)

    def _get_body(self, msg) -> str:
        """Extract plain text from email message."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == 'text/plain':
                    try:
                        charset = part.get_content_charset() or 'utf-8'
                        body += part.get_payload(decode=True).decode(charset, errors='replace')
                    except Exception:
                        pass
        else:
            try:
                charset = msg.get_content_charset() or 'utf-8'
                body = msg.get_payload(decode=True).decode(charset, errors='replace')
            except Exception:
                pass
        return body[:3000]

    def fetch_inbox(self, count: int = 20) -> List[Dict]:
        """Fetch recent emails from inbox."""
        if not self._ensure_connected():
            return []
        try:
            self._mail.select("INBOX")
            # Use SINCE to avoid loading 1M+ messages from large inboxes
            import datetime as _dt
            _since = (_dt.date.today() - _dt.timedelta(days=30)).strftime("%d-%b-%Y")
            _, data = self._mail.search(None, f"SINCE {_since}")
            ids = data[0].split()
            ids = ids[-count:] if len(ids) > count else ids
            ids = list(reversed(ids))  # newest first

            emails = []
            for uid in ids[:count]:
                try:
                    _, msg_data = self._mail.fetch(uid, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])
                    subject = self._decode_header(msg.get("Subject", ""))
                    sender = self._decode_header(msg.get("From", ""))
                    date = msg.get("Date", "")
                    body = self._get_body(msg)
                    emails.append({
                        "id": uid.decode(),
                        "subject": subject[:100],
                        "from": sender[:80],
                        "date": date[:30],
                        "body": body[:500],
                        "has_key": bool(re.search(
                            r'(sk-[a-zA-Z0-9_-]{20,}|gsk_[a-zA-Z0-9]{20,}|'
                            r'[a-zA-Z0-9]{32,}(?:key|token|secret))',
                            body, re.I
                        )),
                    })
                except Exception as e:
                    log.warning("EmailAgent: failed to parse email %s: %s", uid, e)

            self._inbox_cache = emails
            self._last_fetch = time.time()
            log.info("EmailAgent: fetched %d emails", len(emails))
            return emails
        except Exception as e:
            log.error("EmailAgent: fetch_inbox error: %s", e)
            return []

    def extract_api_keys(self) -> List[Dict]:
        """Search inbox for API keys from known providers."""
        if not self._ensure_connected():
            return []

        found_keys = []
        # Search for emails from known providers
        providers = [
            ("openai", "OpenAI", r'sk-proj-[a-zA-Z0-9_-]{80,}'),
            ("openai", "OpenAI", r'sk-[a-zA-Z0-9]{48}'),
            ("anthropic", "Anthropic/Claude", r'sk-ant-[a-zA-Z0-9_-]{90,}'),
            ("groq", "Groq", r'gsk_[a-zA-Z0-9]{52}'),
            ("deepseek", "DeepSeek", r'sk-[a-zA-Z0-9]{32,}'),
            ("google", "Google/Gemini", r'AIza[a-zA-Z0-9_-]{35}'),
            ("mistral", "Mistral", r'[a-zA-Z0-9]{32}'),
        ]

        try:
            self._mail.select("INBOX")
            emails = self.fetch_inbox(50)

            for em in emails:
                body = em.get('body', '')
                subject = em.get('subject', '')
                sender = em.get('from', '')

                for provider_id, provider_name, pattern in providers:
                    keys = re.findall(pattern, body + ' ' + subject)
                    for key in keys:
                        if len(key) > 15:
                            found_keys.append({
                                "provider": provider_id,
                                "provider_name": provider_name,
                                "key": key,
                                "email_subject": subject[:60],
                                "email_from": sender[:60],
                            })

            if found_keys:
                log.info("EmailAgent: found %d API keys in emails", len(found_keys))
            return found_keys
        except Exception as e:
            log.error("EmailAgent: extract_api_keys error: %s", e)
            return []

    def search_emails(self, query: str) -> List[Dict]:
        """Search emails by subject or sender."""
        if not self._ensure_connected():
            return []
        try:
            self._mail.select("INBOX")
            _, data = self._mail.search(None, f'SUBJECT "{query}"')
            ids = data[0].split()
            if not ids:
                _, data = self._mail.search(None, f'FROM "{query}"')
                ids = data[0].split()
            if not ids:
                # Fallback: search in cache
                query_lower = query.lower()
                return [e for e in self._inbox_cache
                        if query_lower in e.get('subject','').lower()
                        or query_lower in e.get('from','').lower()]

            results = []
            for uid in list(reversed(ids))[:10]:
                try:
                    _, msg_data = self._mail.fetch(uid, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])
                    subject = self._decode_header(msg.get("Subject", ""))
                    sender = self._decode_header(msg.get("From", ""))
                    body = self._get_body(msg)
                    results.append({
                        "id": uid.decode(),
                        "subject": subject[:100],
                        "from": sender[:80],
                        "body": body[:500],
                    })
                except Exception:
                    pass
            return results
        except Exception as e:
            log.error("EmailAgent: search error: %s", e)
            return []

    def status(self) -> Dict:
        """Return email connection status."""
        connected = self._ensure_connected()
        count = 0
        if connected:
            try:
                _, data = self._mail.select("INBOX")
                count = int(data[0]) if data and data[0] else 0
            except Exception:
                pass
        return {
            "connected": connected,
            "address": self._address,
            "inbox_count": count,
            "cached": len(self._inbox_cache),
            "last_fetch": self._last_fetch,
        }

    
    def get_setup_instructions(self) -> str:
        """Instructions to fix email authentication."""
        return (
            "Gmail IMAP требует App Password:\n"
            "1. Зайди на https://myaccount.google.com/security\n"
            "2. Включи 2-Step Verification\n"
            "3. Перейди на https://myaccount.google.com/apppasswords\n"
            "4. Создай пароль приложения для 'Mail' / 'Other'\n"
            "5. Скопируй 16-значный код (xxxx xxxx xxxx xxxx)\n"
            "6. Обнови EMAIL_PASSWORD в /root/my_personal_ai/.env\n"
            "7. Перезапусти: systemctl restart personal-ai\n"
            "\nАльтернативно: отправь код боту и он обновит автоматически"
        )

    def process(self, text: str, source: str = "user", **kwargs) -> str:
            text_lower = text.lower().strip()
    
            if any(w in text_lower for w in ["статус", "status", "подключ"]):
                s = self.status()
                icon = "" if s["connected"] else ""
                return (f"{icon} Email: {s['address']}\n"
                        f"  Подключен: {s['connected']}\n"
                        f"  Писем в inbox: {s['inbox_count']}\n"
                        f"  Кэш: {s['cached']} писем")
    
            if any(w in text_lower for w in ["ключ", "key", "api", "найди ключи", "извлеки"]):
                keys = self.extract_api_keys()
                if not keys:
                    return " Ключи API в почте не найдены"
                lines = [" Найденные API ключи:"]
                for k in keys[:10]:
                    masked = k['key'][:12] + "..." + k['key'][-4:]
                    lines.append(f"  {k['provider_name']}: {masked}")
                    lines.append(f"    От: {k['email_from'][:50]}")
                return "\n".join(lines)
    
            if any(w in text_lower for w in ["inbox", "почту", "письма", "входящие"]):
                emails = self.fetch_inbox(10)
                if not emails:
                    return " Inbox пуст или нет подключения"
                lines = [f" Inbox ({self._address}) — последние {len(emails)} писем:"]
                for e in emails[:10]:
                    key_mark = "" if e.get('has_key') else ""
                    lines.append(f"\n{key_mark} {e['subject'][:60]}")
                    lines.append(f"  От: {e['from'][:50]}")
                    lines.append(f"  {e['date'][:25]}")
                return "\n".join(lines)
    
            if any(w in text_lower for w in ["найди", "поиск", "search"]):
                query = text_lower
                for w in ["найди", "поиск", "search", "в почте", "письмо от"]:
                    query = query.replace(w, "").strip()
                if not query:
                    return "Укажи запрос: найди [текст] в почте"
                results = self.search_emails(query)
                if not results:
                    return f" По запросу '{query}' ничего не найдено"
                lines = [f" Найдено {len(results)} писем:"]
                for e in results[:5]:
                    lines.append(f"\n {e['subject'][:60]}")
                    lines.append(f"  От: {e['from'][:50]}")
                return "\n".join(lines)
    
            return (
                f" EmailAgent [{self._address}]\n\n"
                f"Команды:\n"
                f"  входящие — показать inbox\n"
                f"  найди ключи — поиск API ключей в письмах\n"
                f"  найди [запрос] — поиск по теме/отправителю\n"
                f"  статус — состояние подключения"
            )
    