---
name: Resend email via Replit connector
description: How transactional email actually sends (connector token format, verified sender) and the password-reset anti-enumeration contract.
---

# Resend email + password reset

## Replit connectors proxy token format (the silent-failure trap)
When fetching connector secrets from `https://$REPLIT_CONNECTORS_HOSTNAME/api/v2/connection`,
the `X_REPLIT_TOKEN` header VALUE must be prefixed with its type:
- `repl <REPL_IDENTITY>`        in a running repl (dev)
- `depl <WEB_REPL_RENEWAL>`     in a deployment (prod)

Sending the raw token (no prefix) returns `401 Invalid X-Replit-Token header
format, expecting "${type} ${token}"`. The connector lookup then returns no key,
so email silently never sends.
**Why:** this bug made *all* prod email fail; password reset then fell back to an
insecure inline-token response. There is no `RESEND_API_KEY` env in prod, so the
connector path is the only one — get the header right.

## Sender must be the verified brand domain, not the connector's from_email
The Resend connection exposes `settings.from_email`, but that is whatever the user
typed at setup and may be unverifiable (here it was a personal `outlook.com`, which
Resend rejects with `403 domain not verified`). Send from the verified brand domain
(`hello@watchsmart.uk`, EMAIL_FROM env override) — it is verified in Resend and
returns 200. **Do not** auto-use the connector from_email.
Test deliverability with a raw POST to `api.resend.com/emails` from each candidate
sender to `delivered@resend.dev` (Resend's test sink) — 200 = accepted, 403 = sender
domain not verified.

## Password-reset response contract (anti-enumeration)
`/api/auth/forgot-password` MUST return a byte-identical body for existing vs
non-existing emails in production (`{ok, message}` only). Never put a `delivery`
flag or token in the prod response — a shape differential leaks account existence.
The inline reset token/url is dev-only and gated fail-closed: only emitted when
positively in dev (`REPLIT_DEPLOYMENT != "1"` AND `REPLIT_DEV_DOMAIN` set), so any
ambiguous/unknown env is treated as prod.

## Absolute reset links
Email links must be absolute. Origin resolves: `PUBLIC_APP_URL` env →
`ALLOWED_ORIGINS` → `REPLIT_DEV_DOMAIN` → `request.base_url`. `PUBLIC_APP_URL` is
set in the production env to the live deploy URL so prod links never go relative.
