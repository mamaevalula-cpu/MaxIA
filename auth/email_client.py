# -*- coding: utf-8 -*-
"""
auth/email_client.py — Клиент для работы с email через IMAP/SMTP.

Умеет:
  • Подключаться к почте через IMAP
  • Читать письма (в т.ч. коды подтверждения)
  • Ждать новых писем (polling)
  • Отправлять письма через SMTP
  • Отправлять письма через Resend.com API (приоритетный метод)
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
import smtplib
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Callable, Dict, List, Optional, Tuple

from core.config import cfg
from core.secret_manager import SecretManager

log = logging.getLogger("auth.email")


class EmailMessage:
    """Простая обёртка для письма."""
    def __init__(self, msg_id: str, subject: str, sender: str,
                 body: str, date: str = ""):
        self.msg_id  = msg_id
        self.subject = subject
        self.sender  = sender
        self.body    = body
        self.date    = date

    def find_code(self, length: int = 6) -> Optional[str]:
        """Найти числовой код подтверждения в теле письма."""
        text = self.subject + " " + self.body
        # Ищем числа нужной длины
        patterns = [
            rf'\b(\d{{{length}}})\b',
            rf'код[:\s]+(\d{{{length}}})',
            rf'code[:\s]+(\d{{{length}}})',
            rf'OTP[:\s]+(\d{{{length}}})',
            rf'PIN[:\s]+(\d{{{length}}})',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1)
        return None

    def __repr__(self) -> str:
        return f"<EmailMessage from={self.sender!r} subject={self.subject[:40]!r}>"


class EmailClient:
    """
    Клиент для работы с почтой.
    Поддерживает IMAP (чтение), SMTP (отправка) и Resend API (приоритетная отправка).
    """

    def __init__(self, address: str = "", password: str = "",
                 imap_server: str = "", imap_port: int = 993,
                 smtp_server: str = "", smtp_port: int = 587) -> None:

        self._address = address or cfg.email_address
        self._password = password or cfg.email_password
        self._imap_server = imap_server or cfg.imap_server
        self._imap_port = imap_port or cfg.imap_port
        self._smtp_server = smtp_server or (
            "smtp.gmail.com" if "gmail" in self._imap_server else
            "smtp.mail.ru" if "mail.ru" in self._imap_server else
            self._imap_server.replace("imap.", "smtp.")
        )
        self._smtp_port = smtp_port or 587
        self._imap_conn: Optional[imaplib.IMAP4_SSL] = None
        self._rlock = threading.RLock()

    # ── Подключение ───────────────────────────────────────────────────────────

    def connect(self) -> Tuple[bool, str]:
        """Подключиться к IMAP-серверу."""
        if not self._address or not self._password:
            return False, "Email или пароль не настроены (EMAIL_ADDRESS, EMAIL_PASSWORD в .env)"
        try:
            conn = imaplib.IMAP4_SSL(self._imap_server, self._imap_port)
            conn.login(self._address, self._password)
            self._imap_conn = conn
            log.info("IMAP connected: %s@%s", self._address, self._imap_server)
            return True, "Подключено"
        except Exception as e:
            log.error("IMAP connect failed: %s", e)
            return False, str(e)

    def disconnect(self) -> None:
        if self._imap_conn:
            try:
                self._imap_conn.close()
                self._imap_conn.logout()
            except Exception:
                pass
            self._imap_conn = None

    def is_connected(self) -> bool:
        if not self._imap_conn:
            return False
        try:
            self._imap_conn.noop()
            return True
        except Exception:
            return False

    # ── Чтение писем ─────────────────────────────────────────────────────────

    def get_recent_emails(self, count: int = 10,
                          folder: str = "INBOX") -> List[EmailMessage]:
        """Получить последние письма."""
        if not self._ensure_connected():
            return []
        try:
            with self._rlock:
                self._imap_conn.select(folder)
                _, data = self._imap_conn.search(None, "ALL")
                ids = data[0].split()
                # Берём последние count
                recent_ids = ids[-count:] if len(ids) > count else ids
                messages = []
                for msg_id in reversed(recent_ids):
                    msg = self._fetch_message(msg_id)
                    if msg:
                        messages.append(msg)
                return messages
        except Exception as e:
            log.error("get_recent_emails: %s", e)
            return []

    def search_emails(self, subject: str = "", sender: str = "",
                      unseen_only: bool = False) -> List[EmailMessage]:
        """Поиск писем по критериям."""
        if not self._ensure_connected():
            return []
        criteria = []
        if unseen_only:
            criteria.append("UNSEEN")
        if subject:
            criteria.append(f'SUBJECT "{subject}"')
        if sender:
            criteria.append(f'FROM "{sender}"')
        if not criteria:
            criteria = ["ALL"]

        try:
            with self._rlock:
                self._imap_conn.select("INBOX")
                _, data = self._imap_conn.search(None, *criteria)
                ids = data[0].split()
                messages = []
                for msg_id in reversed(ids[-20:]):
                    msg = self._fetch_message(msg_id)
                    if msg:
                        messages.append(msg)
                return messages
        except Exception as e:
            log.error("search_emails: %s", e)
            return []

    def wait_for_code(self, sender_pattern: str = "",
                      code_length: int = 6,
                      timeout: int = 120) -> Optional[str]:
        """
        Ждать письма с кодом подтверждения.
        Polling каждые 5 секунд до timeout.
        """
        deadline = time.time() + timeout
        log.info("Waiting for confirmation code (timeout=%ds)...", timeout)

        while time.time() < deadline:
            emails = self.search_emails(unseen_only=True)
            for em in emails:
                if sender_pattern and sender_pattern.lower() not in em.sender.lower():
                    continue
                code = em.find_code(code_length)
                if code:
                    log.info("Found code: %s in email from %s", code, em.sender)
                    return code
            time.sleep(5)

        log.warning("Timed out waiting for code")
        return None

    # ── Отправка писем ────────────────────────────────────────────────────────

    def send_email(self, to: str, subject: str, body: str,
                   html: bool = False) -> Tuple[bool, str]:
        """Отправить письмо через SMTP."""
        if not self._address or not self._password:
            return False, "Email не настроен"
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self._address
            msg["To"] = to
            mime_type = "html" if html else "plain"
            msg.attach(MIMEText(body, mime_type, "utf-8"))

            with smtplib.SMTP(self._smtp_server, self._smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(self._address, self._password)
                server.sendmail(self._address, to, msg.as_string())

            log.info("Email sent via SMTP to %s: %s", to, subject)
            return True, "Отправлено"
        except Exception as e:
            log.error("Send email failed: %s", e)
            return False, str(e)

    def send_via_resend(self, to: str | List[str], subject: str, body: str,
                        html: Optional[str] = None) -> Tuple[bool, str]:
        """
        Отправить письмо через Resend.com API.

        Resend — приоритетный метод: надёжная доставка без SMTP-сервера.
        Требует RESEND_API_KEY и OUTREACH_FROM_EMAIL в .env.

        Args:
            to:      адрес получателя (строка или список)
            subject: тема письма
            body:    текстовое тело (fallback если html не задан)
            html:    HTML-тело (опционально, приоритет над body)

        Returns:
            (True, "Sent via Resend (id=...)") или (False, "error text")
        """
        try:
            import resend as _resend
        except ImportError:
            log.warning("resend package not installed; falling back to SMTP")
            return self.send_email(to if isinstance(to, str) else to[0],
                                   subject, body, html=bool(html))

        api_key  = os.getenv("RESEND_API_KEY", "")
        from_addr = os.getenv("OUTREACH_FROM_EMAIL", "audit@maxai.fyi")

        if not api_key:
            log.warning("RESEND_API_KEY not set; falling back to SMTP")
            return self.send_email(to if isinstance(to, str) else to[0],
                                   subject, body, html=bool(html))

        _resend.api_key = api_key
        recipients = [to] if isinstance(to, str) else list(to)

        try:
            params: dict = {
                "from":    from_addr,
                "to":      recipients,
                "subject": subject,
            }
            if html:
                params["html"] = html
            else:
                params["text"] = body

            result = _resend.Emails.send(params)
            email_id = (result.get("id", "unknown")
                        if isinstance(result, dict) else str(result))
            log.info("Resend email sent to %s: %s (id=%s)", recipients, subject, email_id)
            return True, f"Sent via Resend (id={email_id})"
        except Exception as e:
            log.error("Resend send failed: %s", e)
            return False, str(e)

    def send(self, to: str | List[str], subject: str, body: str,
             html: Optional[str] = None,
             prefer_resend: bool = True) -> Tuple[bool, str]:
        """
        Универсальная отправка: сначала пробует Resend, потом SMTP.

        Args:
            to:            получатель(и)
            subject:       тема
            body:          текстовое тело
            html:          HTML-тело (опционально)
            prefer_resend: True — сначала Resend, при ошибке — SMTP
        """
        if prefer_resend and os.getenv("RESEND_API_KEY"):
            ok, msg = self.send_via_resend(to, subject, body, html=html)
            if ok:
                return ok, msg
            log.warning("Resend failed (%s), falling back to SMTP", msg)

        addr = to if isinstance(to, str) else (to[0] if to else "")
        return self.send_email(addr, subject, body, html=bool(html))

    # ── Вспомогательные ──────────────────────────────────────────────────────

    def _ensure_connected(self) -> bool:
        if not self.is_connected():
            ok, _ = self.connect()
            return ok
        return True

    def _fetch_message(self, msg_id: bytes) -> Optional[EmailMessage]:
        try:
            _, data = self._imap_conn.fetch(msg_id, "(RFC822)")
            raw = data[0][1]
            msg = email.message_from_bytes(raw)

            subject = self._decode_header(msg.get("Subject", ""))
            sender  = self._decode_header(msg.get("From", ""))
            date    = msg.get("Date", "")
            body    = self._get_body(msg)

            return EmailMessage(
                msg_id=msg_id.decode(),
                subject=subject, sender=sender,
                body=body, date=date
            )
        except Exception as e:
            log.debug("Fetch message error: %s", e)
            return None

    def _decode_header(self, header: str) -> str:
        try:
            from email.header import decode_header
            parts = decode_header(header)
            result = []
            for text, charset in parts:
                if isinstance(text, bytes):
                    result.append(text.decode(charset or "utf-8", errors="replace"))
                else:
                    result.append(text)
            return "".join(result)
        except Exception:
            return str(header)

    def _get_body(self, msg) -> str:
        """Извлечь текстовое тело письма."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    try:
                        charset = part.get_content_charset() or "utf-8"
                        body += part.get_payload(decode=True).decode(charset, errors="replace")
                    except Exception:
                        pass
        else:
            try:
                charset = msg.get_content_charset() or "utf-8"
                body = msg.get_payload(decode=True).decode(charset, errors="replace")
            except Exception:
                body = str(msg.get_payload())
        return body[:5000]
