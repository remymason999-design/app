"""Transactional email via the Resend connector.

Fetches the Resend API key from the Replit connectors proxy (no env vars
required) and sends through Resend's REST API. All sends are best-effort:
if the connector isn't set up, sending is logged as a warning and the
caller continues. Never raises into request handlers.
"""
from __future__ import annotations

import os
import time
import logging
from typing import Optional

import httpx

logger = logging.getLogger("watchsmart.email")

DEFAULT_FROM = os.environ.get("EMAIL_FROM", "WatchSmart <hello@watchsmart.uk>")
RESEND_API = "https://api.resend.com/emails"

_CACHED_KEY: Optional[str] = None
_CACHED_FROM: Optional[str] = None
_CACHED_AT: float = 0.0
_CACHE_TTL = 300  # 5 min


def _connector_token() -> Optional[str]:
    """Build the X_REPLIT_TOKEN value for the connectors proxy.

    The proxy expects the value as "${type} ${token}":
      - "repl <REPL_IDENTITY>"      in a running repl (dev)
      - "depl <WEB_REPL_RENEWAL>"   in a deployment (prod)
    """
    repl_identity = os.environ.get("REPL_IDENTITY")
    if repl_identity:
        return f"repl {repl_identity}"
    web_renewal = os.environ.get("WEB_REPL_RENEWAL")
    if web_renewal:
        return f"depl {web_renewal}"
    return None


async def _fetch_resend_credentials() -> tuple[Optional[str], Optional[str]]:
    """Resolve (api_key, from_email).

    API key priority:
      1. RESEND_API_KEY env var (manual override / production).
      2. Replit connectors proxy (preferred — set up via integration).
    from_email is read from the connector settings when available so we always
    send from a sender Resend has verified for this account.
    Returns (None, None) if no key can be resolved.
    """
    global _CACHED_KEY, _CACHED_FROM, _CACHED_AT
    env_key = os.environ.get("RESEND_API_KEY")

    if _CACHED_KEY and (time.time() - _CACHED_AT) < _CACHE_TTL:
        return _CACHED_KEY, _CACHED_FROM

    key: Optional[str] = env_key
    from_email: Optional[str] = None

    host = os.environ.get("REPLIT_CONNECTORS_HOSTNAME") or os.environ.get("CONNECTORS_HOSTNAME")
    token = _connector_token()
    if host and token:
        url = f"https://{host}/api/v2/connection"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    url,
                    params={"include_secrets": "true", "connector_names": "resend"},
                    headers={"X_REPLIT_TOKEN": token, "Accept": "application/json"},
                )
            if resp.status_code == 200:
                items = resp.json().get("items") or []
                if items:
                    settings = items[0].get("settings") or {}
                    from_email = settings.get("from_email") or settings.get("fromEmail")
                    if not key:
                        key = settings.get("api_key") or settings.get("apiKey")
            else:
                logger.warning("connector lookup failed: %s %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.warning("connector lookup error: %s", exc)

    if key:
        _CACHED_KEY = key
        _CACHED_FROM = from_email
        _CACHED_AT = time.time()
    return key, from_email


async def _fetch_resend_api_key() -> Optional[str]:
    """Back-compat shim — resolve just the API key."""
    key, _ = await _fetch_resend_credentials()
    return key


def _resolve_from() -> str:
    """Sender address.

    EMAIL_FROM env overrides; otherwise the verified brand sender (DEFAULT_FROM,
    e.g. hello@watchsmart.uk). We deliberately do NOT use the connector's
    from_email — that field is whatever the user typed during connector setup
    and is often an unverifiable address (e.g. a personal outlook.com), which
    Resend rejects with a 403. The brand domain is verified in Resend.
    """
    return os.environ.get("EMAIL_FROM") or DEFAULT_FROM


async def send_email(*, to: str, subject: str, html: str, text: Optional[str] = None,
                     reply_to: Optional[str] = "support@watchsmart.uk",
                     idempotency_key: Optional[str] = None) -> bool:
    """Send a transactional email. Returns True on success, False otherwise.

    Never raises — logs and returns False so callers can degrade gracefully.
    """
    api_key, _ = await _fetch_resend_credentials()
    if not api_key:
        logger.warning("Email NOT sent (no Resend API key) — to=%s subject=%r", to, subject)
        return False
    payload = {
        "from": _resolve_from(),
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text
    if reply_to:
        payload["reply_to"] = reply_to
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            if idempotency_key:
                headers["Idempotency-Key"] = idempotency_key[:256]
            resp = await client.post(
                RESEND_API,
                json=payload,
                headers=headers,
            )
        if resp.status_code >= 300:
            logger.warning("Resend send failed %s: %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as exc:
        logger.warning("Resend send error to=%s: %s", to, exc)
        return False


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def _wrapper(title: str, body_html: str) -> str:
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#0b0b0d;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#f5f5f5;">
  <div style="max-width:560px;margin:0 auto;padding:32px 24px;">
    <div style="font-size:11px;letter-spacing:0.25em;text-transform:uppercase;color:#a0a0a0;margin-bottom:24px;">WatchSmart</div>
    <h1 style="font-size:28px;font-weight:600;margin:0 0 16px;color:#fafafa;">{title}</h1>
    <div style="font-size:15px;line-height:1.6;color:#d4d4d4;">{body_html}</div>
    <div style="margin-top:40px;padding-top:24px;border-top:1px solid #27272a;font-size:12px;color:#71717a;">
      WatchSmart · support@watchsmart.uk<br/>
      Reply to this email if you need a hand.
    </div>
  </div>
</body></html>"""


async def send_welcome_email(to: str, name: str) -> bool:
    name_safe = (name or "there").split(" ")[0]
    body = f"""
      <p>Hey {name_safe},</p>
      <p>Welcome to WatchSmart — the app that learns what you actually want to watch.</p>
      <p>Here's how to get going:</p>
      <ul>
        <li>Pick your streaming services</li>
        <li>Swipe right on what looks good, left on what doesn't</li>
        <li>We'll get sharper every swipe</li>
      </ul>
      <p style="margin-top:24px;">Happy watching.</p>
      <p>— The WatchSmart team</p>
    """
    return await send_email(
        to=to,
        subject="Welcome to WatchSmart",
        html=_wrapper("Welcome to WatchSmart", body),
        text=f"Hey {name_safe}, welcome to WatchSmart. Swipe right on what looks good, left on what doesn't. — The WatchSmart team",
    )


async def send_password_reset_email(to: str, reset_url: str, expires_in_min: int = 60) -> bool:
    body = f"""
      <p>We received a request to reset your WatchSmart password.</p>
      <p>This link expires in {expires_in_min} minutes and can only be used once:</p>
      <p style="margin:24px 0;">
        <a href="{reset_url}" style="display:inline-block;background:#f59e0b;color:#0b0b0d;padding:14px 24px;border-radius:12px;text-decoration:none;font-weight:600;">Set a new password</a>
      </p>
      <p style="font-size:13px;color:#a1a1aa;">Or paste this link into your browser:<br/><span style="word-break:break-all;color:#d4d4d4;">{reset_url}</span></p>
      <p style="margin-top:24px;font-size:13px;color:#a1a1aa;">Didn't request this? You can safely ignore this email — your password won't change.</p>
    """
    return await send_email(
        to=to,
        subject="Reset your WatchSmart password",
        html=_wrapper("Reset your password", body),
        text=f"Reset your WatchSmart password (expires in {expires_in_min} min): {reset_url}",
    )
