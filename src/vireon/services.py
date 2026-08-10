from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .domain import PLANS, DomainError, PlanCode, calculate_price_kopecks, referral_month_bonus
from .models import (
    AuditLog,
    Payment,
    PaymentStatus,
    ReferralReward,
    StaffRole,
    StaffUser,
    Subscription,
    SubscriptionKind,
    Ticket,
    TicketMessage,
    User,
    VpnNode,
    ensure_utc,
)
from .security import hash_password


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _public_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4).upper()}"


def _subscription_token() -> str:
    return secrets.token_urlsafe(42)


def _referral_code() -> str:
    return f"vrn_{secrets.token_urlsafe(7).replace('-', '').replace('_', '')[:10]}"


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def get_or_create_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    referral_code: str | None = None,
) -> User:
    user = await get_user_by_telegram_id(session, telegram_id)
    if user is None:
        referrer_id = None
        if referral_code:
            referrer = await session.scalar(select(User).where(User.referral_code == referral_code))
            if referrer and referrer.telegram_id != telegram_id:
                referrer_id = referrer.id
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            referral_code=_referral_code(),
            referrer_id=referrer_id,
        )
        session.add(user)
    else:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
    await session.commit()
    await session.refresh(user)
    return user


async def get_subscription(session: AsyncSession, user_id: int) -> Subscription | None:
    return await session.scalar(select(Subscription).where(Subscription.user_id == user_id))


async def _ensure_subscription(
    session: AsyncSession,
    user: User,
    *,
    plan: PlanCode,
    kind: SubscriptionKind,
    device_limit: int,
) -> Subscription:
    subscription = await get_subscription(session, user.id)
    if subscription is None:
        subscription = Subscription(
            public_id=_public_id("VRN-SUB"),
            user_id=user.id,
            token=_subscription_token(),
            plan_code=plan,
            kind=kind,
            device_limit=device_limit,
            starts_at=now_utc(),
            expires_at=now_utc(),
        )
        session.add(subscription)
        await session.flush()
    return subscription


async def activate_trial(session: AsyncSession, user: User) -> Subscription:
    settings = get_settings()
    if user.trial_used:
        raise DomainError("Пробный период уже был использован")

    subscription = await _ensure_subscription(
        session,
        user,
        plan=PlanCode.MINI,
        kind=SubscriptionKind.TRIAL,
        device_limit=settings.trial_device_limit,
    )
    current = now_utc()
    if ensure_utc(subscription.expires_at) > current and not subscription.cancelled:
        raise DomainError("У вас уже есть активная подписка")

    subscription.kind = SubscriptionKind.TRIAL
    subscription.plan_code = PlanCode.MINI
    subscription.device_limit = settings.trial_device_limit
    subscription.starts_at = current
    subscription.expires_at = current + timedelta(days=settings.trial_days)
    subscription.cancelled = False
    user.trial_used = True
    await session.commit()
    await session.refresh(subscription)
    return subscription


async def create_mock_payment(
    session: AsyncSession, user: User, plan: PlanCode, days: int
) -> Payment:
    settings = get_settings()
    if settings.payment_mode != "mock":
        raise DomainError("Тестовые платежи отключены")
    amount = calculate_price_kopecks(plan, days)
    payment = Payment(
        public_id=_public_id("VRN-PAY"),
        user_id=user.id,
        plan_code=plan,
        days=days,
        amount_kopecks=amount,
        provider="mock",
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)
    return payment


async def _extend_subscription(
    session: AsyncSession,
    user: User,
    days: int,
    *,
    plan: PlanCode | None = None,
    kind: SubscriptionKind | None = None,
    device_limit: int | None = None,
) -> Subscription:
    fallback_plan = plan or PlanCode.MINI
    fallback_limit = device_limit or PLANS[fallback_plan].device_limit
    subscription = await _ensure_subscription(
        session,
        user,
        plan=fallback_plan,
        kind=kind or SubscriptionKind.REFERRAL,
        device_limit=fallback_limit,
    )
    current = now_utc()
    expires_at = ensure_utc(subscription.expires_at)
    base = expires_at if expires_at > current else current
    subscription.expires_at = base + timedelta(days=days)
    subscription.cancelled = False
    if plan is not None:
        subscription.plan_code = plan
    if kind is not None:
        subscription.kind = kind
    if device_limit is not None:
        subscription.device_limit = device_limit
    return subscription


async def confirm_mock_payment(session: AsyncSession, payment: Payment) -> Subscription:
    if payment.status == PaymentStatus.PAID:
        subscription = await get_subscription(session, payment.user_id)
        if subscription is None:
            raise DomainError("Подписка не найдена после уже подтвержденного платежа")
        return subscription
    if payment.status != PaymentStatus.PENDING:
        raise DomainError("Платёж нельзя подтвердить")

    user = await session.get(User, payment.user_id)
    if user is None:
        raise DomainError("Пользователь не найден")

    previous_paid_count = await session.scalar(
        select(func.count(Payment.id)).where(
            Payment.user_id == user.id,
            Payment.status == PaymentStatus.PAID,
            Payment.id != payment.id,
        )
    )
    first_paid_purchase = (previous_paid_count or 0) == 0

    plan = PLANS[payment.plan_code]
    subscription = await _extend_subscription(
        session,
        user,
        payment.days,
        plan=payment.plan_code,
        kind=SubscriptionKind.PAID,
        device_limit=plan.device_limit,
    )
    payment.status = PaymentStatus.PAID
    payment.paid_at = now_utc()

    if user.referrer_id and not payment.referral_processed and payment.days >= 30:
        referrer = await session.get(User, user.referrer_id)
        if referrer is not None:
            monthly_bonus = referral_month_bonus(payment.days)
            if first_paid_purchase:
                await _extend_subscription(session, referrer, 5)
                session.add(
                    ReferralReward(
                        referrer_user_id=referrer.id,
                        referred_user_id=user.id,
                        payment_id=payment.id,
                        recipient_user_id=referrer.id,
                        kind="first_purchase_referrer",
                        days=5,
                    )
                )
                await _extend_subscription(session, user, 2)
                session.add(
                    ReferralReward(
                        referrer_user_id=referrer.id,
                        referred_user_id=user.id,
                        payment_id=payment.id,
                        recipient_user_id=user.id,
                        kind="first_purchase_referred",
                        days=2,
                    )
                )
            if monthly_bonus:
                await _extend_subscription(session, referrer, monthly_bonus)
                session.add(
                    ReferralReward(
                        referrer_user_id=referrer.id,
                        referred_user_id=user.id,
                        payment_id=payment.id,
                        recipient_user_id=referrer.id,
                        kind="paid_months",
                        days=monthly_bonus,
                    )
                )
        payment.referral_processed = True

    await session.commit()
    await session.refresh(subscription)
    return subscription


async def create_ticket(
    session: AsyncSession,
    user: User,
    *,
    category: str,
    subject: str,
    text: str,
) -> Ticket:
    ticket = Ticket(
        public_id=_public_id("VRN-TKT"),
        user_id=user.id,
        category=category,
        subject=subject[:160],
    )
    session.add(ticket)
    await session.flush()
    session.add(
        TicketMessage(
            ticket_id=ticket.id,
            author_type="user",
            author_user_id=user.id,
            text=text,
        )
    )
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def referral_stats(session: AsyncSession, user: User) -> dict[str, int]:
    invited = await session.scalar(select(func.count(User.id)).where(User.referrer_id == user.id))
    rewarded_days = await session.scalar(
        select(func.coalesce(func.sum(ReferralReward.days), 0)).where(
            ReferralReward.recipient_user_id == user.id
        )
    )
    paid_referrals = await session.scalar(
        select(func.count(func.distinct(Payment.user_id)))
        .join(User, User.id == Payment.user_id)
        .where(User.referrer_id == user.id, Payment.status == PaymentStatus.PAID)
    )
    return {
        "invited": int(invited or 0),
        "paid": int(paid_referrals or 0),
        "rewarded_days": int(rewarded_days or 0),
    }


async def enabled_vpn_nodes(session: AsyncSession) -> list[VpnNode]:
    result = await session.scalars(
        select(VpnNode).where(VpnNode.enabled.is_(True)).order_by(VpnNode.priority, VpnNode.name)
    )
    return list(result)


async def bootstrap_owner(session: AsyncSession) -> None:
    settings = get_settings()
    if not settings.bootstrap_owner_username or not settings.bootstrap_owner_password:
        return
    existing = await session.scalar(
        select(StaffUser).where(StaffUser.username == settings.bootstrap_owner_username)
    )
    if existing:
        return
    owner = StaffUser(
        username=settings.bootstrap_owner_username,
        password_hash=hash_password(settings.bootstrap_owner_password),
        role=StaffRole.DEVELOPER,
    )
    session.add(owner)
    await session.flush()
    session.add(
        AuditLog(
            staff_user_id=owner.id,
            action="bootstrap_owner",
            entity_type="staff_user",
            entity_id=owner.id,
            details="Initial developer account created from environment variables",
        )
    )
    await session.commit()
