from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from vireon.domain import DomainError, PlanCode
from vireon.models import Base, ReferralReward
from vireon.services import (
    activate_trial,
    confirm_mock_payment,
    create_mock_payment,
    get_or_create_user,
    get_subscription,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db_session:
        yield db_session
    await engine.dispose()


@pytest.mark.asyncio
async def test_trial_can_only_be_used_once(session) -> None:
    user = await get_or_create_user(
        session,
        telegram_id=1001,
        username="trial_user",
        first_name="Trial",
        last_name=None,
    )
    subscription = await activate_trial(session, user)
    assert subscription.expires_at - subscription.starts_at >= timedelta(days=2, hours=23)

    with pytest.raises(DomainError):
        await activate_trial(session, user)


@pytest.mark.asyncio
async def test_first_month_referral_rewards_both_users(session) -> None:
    referrer = await get_or_create_user(
        session,
        telegram_id=2001,
        username="referrer",
        first_name="Referrer",
        last_name=None,
    )
    referred = await get_or_create_user(
        session,
        telegram_id=2002,
        username="referred",
        first_name="Referred",
        last_name=None,
        referral_code=referrer.referral_code,
    )
    payment = await create_mock_payment(session, referred, PlanCode.STANDARD, 30)
    await confirm_mock_payment(session, payment)

    referrer_subscription = await get_subscription(session, referrer.id)
    referred_subscription = await get_subscription(session, referred.id)
    assert referrer_subscription is not None
    assert referred_subscription is not None

    referrer_days = await session.scalar(
        select(func.sum(ReferralReward.days)).where(
            ReferralReward.recipient_user_id == referrer.id
        )
    )
    referred_days = await session.scalar(
        select(func.sum(ReferralReward.days)).where(
            ReferralReward.recipient_user_id == referred.id
        )
    )
    assert referrer_days == 6
    assert referred_days == 2
