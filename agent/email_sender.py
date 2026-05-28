"""Email senders: Gmail API (OAuth) and SMTP fallback.

Two backends are provided because OAuth onboarding is the #1 thing that
can eat 30 minutes during a live demo. SMTP via a Gmail App Password is
the reliable "always works" path; the Gmail API path is the one that
shows you understand modern OAuth scopes and offline tokens.

All sending respects a global ``--dry-run`` flag that simply prints the
rendered email and returns. Nothing leaves the machine in dry-run mode.
"""
from __future__ import annotations

import base64
import os
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


@dataclass
class SendResult:
    ok: bool
    backend: str
    detail: str


def _build_mime(subject: str, html: str, sender: str, recipient: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText("This email requires an HTML-capable viewer.", "plain"))
    msg.attach(MIMEText(html, "html"))
    return msg


def send_dry_run(subject: str, html: str, recipient: str) -> SendResult:
    print("=" * 72)
    print(f"DRY RUN — would send to: {recipient}")
    print(f"Subject: {subject}")
    print("-" * 72)
    print(html)
    print("=" * 72)
    return SendResult(ok=True, backend="dry-run", detail="printed to stdout")


def send_via_smtp(subject: str, html: str, recipient: str) -> SendResult:
    """Send via Gmail SMTP using an App Password.

    Required env vars:
      SMTP_USER           — Gmail address
      SMTP_APP_PASSWORD   — 16-char App Password (NOT the account password)
    """
    user = os.environ.get("SMTP_USER")
    pwd = os.environ.get("SMTP_APP_PASSWORD")
    if not user or not pwd:
        return SendResult(False, "smtp", "SMTP_USER / SMTP_APP_PASSWORD not set")

    msg = _build_mime(subject, html, sender=user, recipient=recipient)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(user, pwd)
            s.sendmail(user, [recipient], msg.as_string())
        return SendResult(True, "smtp", f"sent to {recipient}")
    except Exception as e:  # noqa: BLE001 — surface any SMTP error to the caller
        return SendResult(False, "smtp", f"SMTP error: {e}")


def send_via_gmail_api(subject: str, html: str, recipient: str) -> SendResult:
    """Send via the Gmail REST API using OAuth.

    Expects ``credentials.json`` (Desktop-app client) in the repo root and
    writes/refreshes ``token.json`` after the first browser consent.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        return SendResult(False, "gmail-api", "google-api-python-client / google-auth-oauthlib not installed")

    scopes = ["https://www.googleapis.com/auth/gmail.send"]
    creds_path = Path("credentials.json")
    token_path = Path("token.json")

    if not creds_path.exists():
        return SendResult(False, "gmail-api", "credentials.json missing — download a Desktop OAuth client from GCP")

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), scopes)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    service = build("gmail", "v1", credentials=creds)
    sender = os.environ.get("GMAIL_SENDER", "me")
    mime_msg = _build_mime(subject, html, sender=sender, recipient=recipient)
    raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
    try:
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return SendResult(True, "gmail-api", f"sent to {recipient}")
    except Exception as e:  # noqa: BLE001
        return SendResult(False, "gmail-api", f"Gmail API error: {e}")


def send_email(subject: str, html: str, recipient: str, sender: str = "gmail-api",
               dry_run: bool = False) -> SendResult:
    """Single entry point used by the agent's tool layer."""
    if dry_run:
        return send_dry_run(subject, html, recipient)
    if sender == "smtp":
        return send_via_smtp(subject, html, recipient)
    if sender == "gmail-api":
        return send_via_gmail_api(subject, html, recipient)
    return SendResult(False, sender, f"unknown sender backend: {sender}")
