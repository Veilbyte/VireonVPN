from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import __version__
from .config import get_settings
from .db import SessionLocal, get_session, init_db
from .domain import PLANS, PRESET_DAYS, calculate_price_kopecks
from .models import Payment, StaffUser, Subscription, Ticket, User, ensure_utc
from .security import create_admin_token, decode_admin_token, verify_password
from .services import bootstrap_owner, enabled_vpn_nodes

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    async with SessionLocal() as session:
        await bootstrap_owner(session)
    yield


app = FastAPI(title="Vireon API", version=__version__, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/v1/plans")
async def plans() -> dict:
    return {
        "plans": [
            {
                "code": plan.code,
                "title": plan.title,
                "monthly_price_kopecks": plan.monthly_price_kopecks,
                "device_limit": plan.device_limit,
                "presets": [
                    {"days": days, "price_kopecks": calculate_price_kopecks(plan.code, days)}
                    for days in PRESET_DAYS
                ],
            }
            for plan in PLANS.values()
        ]
    }


@app.get("/s/{token}", response_class=PlainTextResponse)
async def happ_subscription(token: str, session: AsyncSession = Depends(get_session)) -> Response:
    subscription = await session.scalar(select(Subscription).where(Subscription.token == token))
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")

    subscription_expires_at = ensure_utc(subscription.expires_at)
    expire = int(subscription_expires_at.timestamp())
    active = not subscription.cancelled and subscription_expires_at > datetime.now(timezone.utc)
    nodes = await enabled_vpn_nodes(session) if active else []

    body_lines = [
        "#profile-title: Vireon VPN",
        "#profile-update-interval: 12",
        f"#subscription-userinfo: upload=0; download=0; total=0; expire={expire}",
    ]
    if settings.support_url:
        body_lines.append(f"#support-url: {settings.support_url}")
    body_lines.extend(node.config_uri for node in nodes)

    headers = {
        "profile-title": "Vireon VPN",
        "profile-update-interval": "12",
        "subscription-userinfo": f"upload=0; download=0; total=0; expire={expire}",
        "Cache-Control": "no-store",
    }
    if settings.support_url:
        headers["support-url"] = settings.support_url
    return PlainTextResponse("\n".join(body_lines) + "\n", headers=headers)


def _login_html(error: str | None = None) -> str:
    error_html = f'<p class="error">{error}</p>' if error else ""
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Vireon Control</title><style>
body{{font-family:Inter,system-ui,sans-serif;background:#070707;color:#fff;display:grid;place-items:center;min-height:100vh;margin:0}}
.card{{width:min(380px,calc(100% - 40px));padding:32px;border:1px solid #2b2b2b;border-radius:22px;background:#111}}
h1{{margin:0 0 8px}}p{{color:#aaa}}label{{display:block;margin:16px 0 6px;color:#bbb}}input{{box-sizing:border-box;width:100%;padding:13px;border-radius:11px;border:1px solid #333;background:#0a0a0a;color:#fff}}
button{{width:100%;margin-top:22px;padding:13px;border:0;border-radius:11px;background:#fff;color:#000;font-weight:700;cursor:pointer}}.error{{color:#ff7a7a}}
</style></head><body><main class="card"><h1>Vireon Control</h1><p>Вход для персонала проекта</p>{error_html}
<form method="post"><label>Логин</label><input name="username" autocomplete="username" required>
<label>Пароль</label><input type="password" name="password" autocomplete="current-password" required>
<button type="submit">Войти</button></form></main></body></html>"""


async def _current_staff(request: Request, session: AsyncSession) -> StaffUser | None:
    token = request.cookies.get("vireon_admin")
    if not token:
        return None
    payload = decode_admin_token(token)
    if not payload or not payload.get("sub"):
        return None
    staff = await session.get(StaffUser, payload["sub"])
    if staff is None or not staff.is_active:
        return None
    return staff


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page() -> str:
    return _login_html()


@app.post("/admin/login")
async def admin_login(
    username: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> Response:
    staff = await session.scalar(select(StaffUser).where(StaffUser.username == username))
    if staff is None or not staff.is_active or not verify_password(password, staff.password_hash):
        return HTMLResponse(_login_html("Неверный логин или пароль"), status_code=401)
    token = create_admin_token(staff.id, staff.role.value)
    response = RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        "vireon_admin",
        token,
        httponly=True,
        samesite="lax",
        secure=settings.environment == "production",
        max_age=43_200,
    )
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    staff = await _current_staff(request, session)
    if staff is None:
        return RedirectResponse("/admin/login", status_code=303)

    users = await session.scalar(select(func.count(User.id))) or 0
    active_subs = await session.scalar(
        select(func.count(Subscription.id)).where(
            Subscription.cancelled.is_(False), Subscription.expires_at > datetime.now(timezone.utc)
        )
    ) or 0
    tickets = await session.scalar(select(func.count(Ticket.id))) or 0
    payments = await session.scalar(select(func.count(Payment.id))) or 0

    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Vireon Control</title><style>
body{{font-family:Inter,system-ui,sans-serif;background:#070707;color:#fff;margin:0;padding:32px}}main{{max-width:1100px;margin:auto}}header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:32px}}small,p{{color:#999}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}}.card{{background:#111;border:1px solid #272727;border-radius:18px;padding:22px}}.num{{font-size:34px;font-weight:800;margin-top:10px}}code{{color:#ddd}}
</style></head><body><main><header><div><h1>Vireon Control</h1><small>v{__version__} · {staff.role.value}</small></div><code>{staff.username}</code></header>
<div class="grid"><section class="card"><p>Пользователи</p><div class="num">{users}</div></section>
<section class="card"><p>Активные подписки</p><div class="num">{active_subs}</div></section>
<section class="card"><p>Тикеты</p><div class="num">{tickets}</div></section>
<section class="card"><p>Платежи</p><div class="num">{payments}</div></section></div>
<section class="card" style="margin-top:14px"><h2>v0.1.0 Foundation</h2><p>Базовая панель уже подключена к общей БД. Следующие разделы: пользователи, подписки, тикеты, сотрудники, VPN-ноды и аудит.</p></section>
</main></body></html>"""
    return HTMLResponse(html)
