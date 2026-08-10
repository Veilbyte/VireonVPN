from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.deep_linking import create_start_link

from .config import get_settings
from .db import SessionLocal, init_db
from .domain import PLANS, PRESET_DAYS, DomainError, PlanCode, calculate_price_kopecks
from .models import Payment, ensure_utc
from .services import (
    activate_trial,
    confirm_mock_payment,
    create_mock_payment,
    create_ticket,
    get_or_create_user,
    get_subscription,
    referral_stats,
)

settings = get_settings()
router = Router()


class CustomDays(StatesGroup):
    waiting_days = State()


class SupportTicket(StatesGroup):
    waiting_text = State()


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛡 Моя подписка", callback_data="subscription")],
            [
                InlineKeyboardButton(text="🎁 Пробный период", callback_data="trial"),
                InlineKeyboardButton(text="💳 Тарифы", callback_data="plans"),
            ],
            [
                InlineKeyboardButton(text="👥 Рефералы", callback_data="referrals"),
                InlineKeyboardButton(text="🆘 Поддержка", callback_data="support"),
            ],
        ]
    )


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="← Главное меню", callback_data="home")]]
    )


@router.message(CommandStart())
async def start(message: Message, bot: Bot) -> None:
    referral_code = None
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) == 2:
            referral_code = parts[1].strip()
    tg = message.from_user
    async with SessionLocal() as session:
        await get_or_create_user(
            session,
            telegram_id=tg.id,
            username=tg.username,
            first_name=tg.first_name,
            last_name=tg.last_name,
            referral_code=referral_code,
        )
    await message.answer(
        "<b>Vireon VPN</b>\n\nVPN-сервис в Telegram. Получите 3 дня для теста, "
        "выберите тариф и подключайте Vireon через Happ.",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "home")
async def home(callback: CallbackQuery) -> None:
    await callback.message.edit_text("<b>Vireon VPN</b>\n\nВыберите раздел:", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "trial")
async def trial(callback: CallbackQuery) -> None:
    async with SessionLocal() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
        )
        try:
            sub = await activate_trial(session, user)
        except DomainError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
    link = f"{settings.public_base_url.rstrip('/')}/s/{sub.token}"
    await callback.message.edit_text(
        "✅ <b>Пробный период активирован</b>\n\n"
        f"Номер: <code>{sub.public_id}</code>\n"
        f"Действует до: <b>{sub.expires_at:%d.%m.%Y %H:%M} UTC</b>\n"
        f"Устройств: <b>{sub.device_limit}</b>\n\n"
        f"Ссылка для Happ:\n<code>{link}</code>",
        reply_markup=back_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "subscription")
async def subscription(callback: CallbackQuery) -> None:
    async with SessionLocal() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
        )
        sub = await get_subscription(session, user.id)
    if sub is None:
        text = "У вас пока нет подписки Vireon. Вы можете активировать пробный период или купить тариф."
    else:
        active = not sub.cancelled and ensure_utc(sub.expires_at) > datetime.now(timezone.utc)
        state = "🟢 Активна" if active else "🔴 Истекла"
        link = f"{settings.public_base_url.rstrip('/')}/s/{sub.token}"
        text = (
            f"<b>{state}</b>\n\nНомер: <code>{sub.public_id}</code>\n"
            f"Тариф: <b>{PLANS[sub.plan_code].title}</b>\n"
            f"Устройства: <b>{sub.device_limit}</b>\n"
            f"До: <b>{sub.expires_at:%d.%m.%Y %H:%M} UTC</b>\n\n"
            f"Happ: <code>{link}</code>"
        )
    await callback.message.edit_text(text, reply_markup=back_menu())
    await callback.answer()


@router.callback_query(F.data == "plans")
async def plans(callback: CallbackQuery) -> None:
    rows = [
        [InlineKeyboardButton(text=f"{plan.title} · {plan.monthly_price_kopecks // 100} ₽/мес", callback_data=f"plan:{plan.code.value}")]
        for plan in PLANS.values()
    ]
    rows.append([InlineKeyboardButton(text="← Главное меню", callback_data="home")])
    await callback.message.edit_text(
        "<b>Тарифы Vireon</b>\n\nМини — 3 устройства\nСтандарт — 5 устройств\nМакс — 8 устройств\n\nВсе тарифы получают доступ ко всем VPN-локациям.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("plan:"))
async def plan_details(callback: CallbackQuery) -> None:
    plan = PlanCode(callback.data.split(":", 1)[1])
    p = PLANS[plan]
    rows = [
        [InlineKeyboardButton(text=f"{days} дней · {calculate_price_kopecks(plan, days) / 100:.2f} ₽", callback_data=f"buy:{plan.value}:{days}")]
        for days in PRESET_DAYS
    ]
    rows.append([InlineKeyboardButton(text="Свой срок", callback_data=f"custom:{plan.value}")])
    rows.append([InlineKeyboardButton(text="← К тарифам", callback_data="plans")])
    await callback.message.edit_text(
        f"<b>Vireon {p.title}</b>\n\nДо {p.device_limit} устройств.\nБазовая цена: {p.monthly_price_kopecks / 100:.0f} ₽ / 30 дней.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("custom:"))
async def custom_days(callback: CallbackQuery, state: FSMContext) -> None:
    plan = PlanCode(callback.data.split(":", 1)[1])
    await state.set_state(CustomDays.waiting_days)
    await state.update_data(plan=plan.value)
    await callback.message.edit_text("Введите количество дней подписки. Минимум — 3 дня.")
    await callback.answer()


@router.message(CustomDays.waiting_days)
async def custom_days_value(message: Message, state: FSMContext) -> None:
    try:
        days = int(message.text or "")
        data = await state.get_data()
        plan = PlanCode(data["plan"])
        price = calculate_price_kopecks(plan, days)
    except (ValueError, KeyError, DomainError) as exc:
        await message.answer(f"Некорректный срок. {exc if isinstance(exc, DomainError) else 'Введите число от 3.'}")
        return
    await state.clear()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Создать платёж · {price / 100:.2f} ₽", callback_data=f"buy:{plan.value}:{days}")],
            [InlineKeyboardButton(text="← Главное меню", callback_data="home")],
        ]
    )
    await message.answer(f"Vireon {PLANS[plan].title}, {days} дней — <b>{price / 100:.2f} ₽</b>", reply_markup=keyboard)


@router.callback_query(F.data.startswith("buy:"))
async def buy(callback: CallbackQuery) -> None:
    _, plan_raw, days_raw = callback.data.split(":", 2)
    plan = PlanCode(plan_raw)
    days = int(days_raw)
    async with SessionLocal() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
        )
        try:
            payment = await create_mock_payment(session, user, plan, days)
        except DomainError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ DEV: подтвердить тестовую оплату", callback_data=f"payok:{payment.id}")],
            [InlineKeyboardButton(text="← Главное меню", callback_data="home")],
        ]
    )
    await callback.message.edit_text(
        f"Платёж <code>{payment.public_id}</code>\n"
        f"Vireon {PLANS[plan].title} · {days} дней\n"
        f"Сумма: <b>{payment.amount_kopecks / 100:.2f} ₽</b>\n\n"
        "Сейчас используется тестовый платёжный шлюз.",
        reply_markup=keyboard,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("payok:"))
async def confirm_payment(callback: CallbackQuery) -> None:
    payment_id = callback.data.split(":", 1)[1]
    async with SessionLocal() as session:
        payment = await session.get(Payment, payment_id)
        if payment is None:
            await callback.answer("Платёж не найден", show_alert=True)
            return
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
        )
        if payment.user_id != user.id:
            await callback.answer("Этот платёж принадлежит другому пользователю", show_alert=True)
            return
        try:
            sub = await confirm_mock_payment(session, payment)
        except DomainError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
    await callback.message.edit_text(
        "✅ <b>Оплата подтверждена</b>\n\n"
        f"Подписка <code>{sub.public_id}</code> активна до {sub.expires_at:%d.%m.%Y %H:%M} UTC.",
        reply_markup=back_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "referrals")
async def referrals(callback: CallbackQuery, bot: Bot) -> None:
    async with SessionLocal() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
        )
        stats = await referral_stats(session, user)
    link = await create_start_link(bot, user.referral_code, encode=False)
    await callback.message.edit_text(
        "<b>Реферальная программа</b>\n\n"
        "За первую покупку друга от 1 месяца: вам +5 дней, другу +2 дня. "
        "Дополнительно вам сразу начисляется +1 день за каждый оплаченный месяц друга.\n\n"
        f"Приглашено: <b>{stats['invited']}</b>\n"
        f"Оплатили: <b>{stats['paid']}</b>\n"
        f"Начислено дней: <b>{stats['rewarded_days']}</b>\n\n"
        f"Ваша ссылка:\n<code>{link}</code>",
        reply_markup=back_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SupportTicket.waiting_text)
    await callback.message.edit_text(
        "<b>Техническая поддержка</b>\n\n"
        "Опишите проблему одним сообщением. В первой версии после отправки будет создан тикет для персонала."
    )
    await callback.answer()


@router.message(SupportTicket.waiting_text)
async def support_text(message: Message, state: FSMContext) -> None:
    text = message.text or message.caption or "Пользователь отправил вложение без текста"
    async with SessionLocal() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        ticket = await create_ticket(
            session,
            user,
            category="other",
            subject=text[:80],
            text=text,
        )
    await state.clear()
    await message.answer(
        f"✅ Тикет <code>{ticket.public_id}</code> создан. Сотрудник поддержки увидит его в системе.",
        reply_markup=main_menu(),
    )


async def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("VIREON_TELEGRAM_BOT_TOKEN is required to run the bot")
    await init_db()
    bot = Bot(
        settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
