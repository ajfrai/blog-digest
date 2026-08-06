#!/usr/bin/env python3
"""
mail_server — a tiny "email me" HTTP endpoint.

A dependency-free (stdlib only) HTTP service that sends email via the reusable
mailer.py library and the SMTP credentials in ~/blog_digest/.blog_digest_env.
Hit it from a phone shortcut, curl, or a browser to email yourself.

Auth: every request must present the token from MAIL_ENDPOINT_TOKEN, either as
  Authorization: Bearer <token>    (preferred)
or as a ?token=<token> query parameter (handy for browser / shortcut links).

Endpoints:
  GET  /health                      -> {"ok": true}
  GET  /send?subject=..&body=..     -> send (query params; easiest from a phone)
  POST /send  {json or form}        -> send (subject, body, to?, html?)

Defaults: recipient is EMAIL_TO (falls back to SMTP_USER); subject defaults to
"Note to self" if omitted; body may be empty.

Run:
  source ~/blog_digest/.blog_digest_env && python3 ~/blog_digest/mail_server.py
  # or: python3 ~/blog_digest/mail_server.py --port 8087
"""

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mailer

DEFAULT_PORT = 8087


def _recipients(explicit):
    if explicit:
        return [r.strip() for r in explicit.split(",") if r.strip()]
    env = os.getenv("EMAIL_TO") or os.getenv("SMTP_USER")
    return [env] if env else []


class Handler(BaseHTTPRequestHandler):
    server_version = "mail_server/1.0"

    # --- helpers -----------------------------------------------------------
    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self, params):
        expected = os.getenv("MAIL_ENDPOINT_TOKEN")
        if not expected:
            return False  # refuse to run unauthenticated
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.startswith("Bearer ") else None
        token = token or (params.get("token", [None])[0])
        return token == expected

    def log_message(self, fmt, *args):
        # Quiet the default per-request stderr noise; keep it one line.
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # --- request handling --------------------------------------------------
    def _handle(self, fields, params):
        if not self._authorized(params):
            self._json(401, {"ok": False, "error": "unauthorized"})
            return

        recipients = _recipients(fields.get("to"))
        if not recipients:
            self._json(400, {"ok": False, "error": "no recipient (set EMAIL_TO or pass to=)"})
            return

        subject = fields.get("subject") or "Note to self"
        text = fields.get("body")
        html = fields.get("html")
        if text is None and html is None:
            text = ""

        try:
            sent = mailer.send_email(
                subject=subject, recipients=recipients, text=text, html=html
            )
        except Exception as e:
            self._json(502, {"ok": False, "error": f"send failed: {e}"})
            return

        self._json(200, {"ok": True, "sent_to": sent, "subject": subject})

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/health":
            self._json(200, {"ok": True})
            return
        if parsed.path == "/send":
            fields = {k: v[0] for k, v in params.items() if k != "token"}
            self._handle(fields, params)
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path != "/send":
            self._json(404, {"ok": False, "error": "not found"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode() if length else ""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()

        if ctype == "application/json":
            try:
                fields = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid JSON body"})
                return
        else:  # form-encoded or anything else
            fields = {k: v[0] for k, v in parse_qs(raw).items()}

        self._handle(fields, params)


def main():
    parser = argparse.ArgumentParser(description="Tiny 'email me' HTTP endpoint.")
    parser.add_argument("--port", type=int, default=int(os.getenv("MAIL_ENDPOINT_PORT", DEFAULT_PORT)))
    parser.add_argument("--host", default=os.getenv("MAIL_ENDPOINT_HOST", "0.0.0.0"))
    parser.add_argument("--env-file", default=str(mailer.DEFAULT_ENV_FILE))
    args = parser.parse_args()

    mailer.load_env_file(args.env_file)

    if not os.getenv("MAIL_ENDPOINT_TOKEN"):
        sys.exit("MAIL_ENDPOINT_TOKEN is not set — refusing to start without auth.")
    try:
        mailer.SMTPConfig.from_env().validate()
    except ValueError as e:
        sys.exit(str(e))

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"mail_server listening on {args.host}:{args.port}  (POST/GET /send, GET /health)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
