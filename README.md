# Vireon VPN

Vireon is a Telegram-first VPN subscription service. The user-facing product lives in a Telegram bot, while Happ is used as the cross-platform VPN client. This repository contains the Vireon control plane: bot, backend API, subscription feed for Happ, database models, referral logic, support tickets and the first staff web panel.

> Current release: **v0.1.0 Foundation**. Real VPN nodes and the production SBP/card payment provider are intentionally not required yet.

## What works in v0.1.0

- automatic user creation by Telegram ID;
- one-time 3-day trial;
- plans: Mini (3 devices / 59 ₽), Standard (5 / 89 ₽), Max (8 / 125 ₽);
- 14 / 30 / 90 / 180 day presets plus a custom duration from 3 days;
- configurable linear price calculation;
- stable Vireon subscription number and token;
- Happ-compatible subscription endpoint with `profile-title`, update interval and expiration metadata;
- VPN-node registry: adding real VLESS/VMess/Trojan/SS/Hysteria links later does not require changing the bot flow;
- mock payment gateway for development;
- referral binding and automatic bonus-day calculation;
- basic support ticket creation;
- staff bootstrap account with Argon2 password hashing and signed admin session;
- minimal `/admin` dashboard;
- PostgreSQL production compose setup and SQLite development fallback.

## Architecture

```text
Telegram user
    |
    v
Vireon Bot -----------+
                      |
                      v
                 Shared domain/services
                      |
          +-----------+-----------+
          |                       |
          v                       v
     PostgreSQL              FastAPI / Admin
                                  |
                                  v
                          /s/{subscription_token}
                                  |
                                  v
                                Happ
                                  |
                                  v
                         Enabled VPN node URIs
```

The VPN transport layer is deliberately data-driven. `vpn_nodes.config_uri` stores the connection URI that Happ receives. Until real VPS nodes are purchased, the table can remain empty and the rest of the service is fully developable.

## Quick start

### Docker

```bash
cp .env.example .env
# Set VIREON_TELEGRAM_BOT_TOKEN and secure admin credentials in .env
docker compose up --build
```

API: `http://localhost:8000`  
Swagger: `http://localhost:8000/docs`  
Admin: `http://localhost:8000/admin`

### Local Python

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
# For a no-PostgreSQL local run, set:
# VIREON_DATABASE_URL=sqlite+aiosqlite:///./vireon.db
uvicorn vireon.api:app --reload
```

In another terminal:

```bash
python -m vireon.bot
```

## First developer account

There is **no password embedded in the repository**. To create the initial Developer account on an empty database, set both:

```env
VIREON_BOOTSTRAP_OWNER_USERNAME=your-login
VIREON_BOOTSTRAP_OWNER_PASSWORD=a-long-unique-password
```

On first API startup the password is hashed with Argon2 and stored in the database. Remove the plaintext bootstrap password from the environment afterwards.

## Development payment flow

`VIREON_PAYMENT_MODE=mock` makes the bot show an explicit `DEV: подтвердить тестовую оплату` button. It exists only to test subscription/referral behavior before a real acquiring provider is selected. Production must switch to a provider implementation and webhook verification.

## Happ feed

Each Vireon account owns a stable endpoint:

```text
GET /s/{token}
```

The response includes profile metadata and then every enabled `vpn_nodes.config_uri`. When no servers exist yet the subscription remains valid but contains no VPN nodes. Once real nodes are added, Happ receives them on the next subscription refresh without issuing a new user link.

## Product decisions intentionally configurable

A few decisions are not final yet and therefore are not hard-wired:

- trial device limit (`VIREON_TRIAL_DEVICE_LIMIT`, currently default `1`);
- final discounts for 3/6-month purchases;
- payment provider;
- Happ limited-link/provider integration;
- exact countries and VPN transports;
- traffic/fair-use rules.

## Security notes

- Never commit `.env` or real Telegram/payment credentials.
- The owner password previously discussed outside the repository must not be reused for production.
- Use a long random `VIREON_JWT_SECRET` in production.
- Put the API behind HTTPS before using real subscription URLs.
- The current `create_all()` bootstrap is convenient for v0.1.0; Alembic migrations are planned before production data is introduced.

## Next milestones

### v0.2.0 — Staff & support
- staff invitations;
- RBAC permissions;
- ticket chat with attachments;
- ticket assignment/escalation/closure and reviews;
- audit log UI.

### v0.3.0 — Billing
- real SBP/card provider;
- verified webhooks and idempotency;
- promo codes and gift subscriptions;
- notification scheduler.

### v0.4.0 — VPN control plane
- node CRUD in admin;
- Happ encrypted/limited links;
- device registry;
- node health monitoring;
- multiple transports and automatic subscription refresh.

### v0.5.0 — Analytics & operations
- dashboard metrics;
- broadcast segmentation;
- referral drill-down;
- server health and incident tools.

### v1.0.0 — First public release
- hardened production deployment;
- real servers and failover;
- completed billing/support/admin flows;
- legal pages and operational monitoring.
