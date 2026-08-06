#!/usr/bin/env python3
"""
mailer — a small, dependency-free email-sending library.

Extracted from blog_digest.py so the SMTP logic can be reused by other
scripts and skills. Uses only the Python standard library (smtplib + email).

Credentials are read from environment variables:

    SMTP_SERVER    (default: smtp.gmail.com)
    SMTP_PORT      (default: 587)
    SMTP_USER      (required — the authenticating account / default From)
    SMTP_PASSWORD  (required — for Gmail, an app password)

The blog_digest project keeps these in ~/blog_digest/.blog_digest_env in
"export KEY=value" form. Call load_env_file() to load them into os.environ
without needing a shell to `source` the file.

Typical use:

    import mailer
    mailer.load_env_file()                 # loads ~/blog_digest/.blog_digest_env
    mailer.send_email(
        subject="Hello",
        recipients="me@example.com",       # str or list[str]
        text="plain text body",
        html="<b>optional html body</b>",
    )
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

DEFAULT_ENV_FILE = Path.home() / "blog_digest" / ".blog_digest_env"


def load_env_file(path=DEFAULT_ENV_FILE, override=False):
    """Load a shell-style env file ("export KEY=value" lines) into os.environ.

    Lines may optionally start with "export ", and values may be quoted.
    Existing environment variables are left untouched unless override=True.
    Returns the dict of keys that were loaded. Silently does nothing if the
    file does not exist.
    """
    path = Path(path)
    loaded = {}
    if not path.exists():
        return loaded

    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
        loaded[key] = value
    return loaded


class SMTPConfig:
    """SMTP connection settings."""

    def __init__(self, server=None, port=None, user=None, password=None):
        self.server = server or os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.port = int(port or os.getenv("SMTP_PORT", "587"))
        self.user = user or os.getenv("SMTP_USER")
        self.password = password or os.getenv("SMTP_PASSWORD")

    @classmethod
    def from_env(cls):
        return cls()

    def validate(self):
        missing = [
            name for name, val in (("SMTP_USER", self.user), ("SMTP_PASSWORD", self.password))
            if not val
        ]
        if missing:
            raise ValueError(
                "Missing SMTP credentials: " + ", ".join(missing)
                + ". Set them in the environment or call load_env_file()."
            )


def build_message(subject, sender, recipient, html=None, text=None, extra_headers=None):
    """Build a MIMEMultipart('alternative') message for a single recipient.

    At least one of `text` or `html` must be provided. When only one is given,
    a minimal fallback is generated for the other part so the message is valid.
    """
    if not text and not html:
        raise ValueError("Provide at least one of `text` or `html`.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    for key, value in (extra_headers or {}).items():
        msg[key] = value

    # Order matters: clients prefer the last part they can render, so attach
    # plain text first and HTML second.
    msg.attach(MIMEText(text or "", "plain"))
    if html:
        msg.attach(MIMEText(html, "html"))
    return msg


def send_messages(messages, config=None):
    """Send already-built email.Message objects over a single SMTP connection.

    Returns the number of messages successfully handed off to the server.
    """
    config = config or SMTPConfig.from_env()
    config.validate()

    sent = 0
    with smtplib.SMTP(config.server, config.port) as server:
        server.starttls()
        server.login(config.user, config.password)
        for msg in messages:
            server.send_message(msg)
            sent += 1
    return sent


def send_email(subject, recipients, html=None, text=None, sender=None,
               config=None, extra_headers=None):
    """Send an email to one or more recipients.

    `recipients` may be a single address string or an iterable of addresses.
    Each recipient gets their own message (separate To: header). Returns the
    list of recipients the message was successfully sent to.
    """
    config = config or SMTPConfig.from_env()
    config.validate()

    if isinstance(recipients, str):
        recipients = [recipients]
    recipients = [r.strip() for r in recipients if r and r.strip()]
    if not recipients:
        raise ValueError("No recipients provided.")

    sender = sender or config.user

    messages = [
        build_message(subject, sender, r, html=html, text=text, extra_headers=extra_headers)
        for r in recipients
    ]
    send_messages(messages, config=config)
    return recipients
