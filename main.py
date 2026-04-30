import asyncio
import logging

import httpx
import psycopg
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ai_advice import generate_ai_advice
from config import BOT_TOKEN
from database import get_location_preferences_for_telegram_id, get_saved_preferences, setup_database, upsert_user
from keyboards import main_menu_keyboard
from onboarding import onboarding_sessions
from onboarding import router as onboarding_router
from onboarding import set_bot
from weather import build_weather_context, get_weather_for_user_from_db_or_fetch

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

set_bot(bot)
dp.include_router(onboarding_router)


@dp.callback_query(F.data == "menu:today")
async def handle_today_menu(callback: CallbackQuery) -> None:
    await callback.answer()

    telegram_id = callback.from_user.id

    try:
        result = await asyncio.to_thread(get_weather_for_user_from_db_or_fetch, telegram_id)
        context = build_weather_context(
            result["weather_json"],
            result["preferences"],
            result["location"],
            day="today",
        )
        message = await asyncio.to_thread(generate_ai_advice, context)
    except httpx.HTTPError:
        logging.exception("weather advice request failed telegram_id=%s", telegram_id)
        await callback.message.answer("I could not prepare the advice right now. Please try again later.")
        return
    except (psycopg.Error, RuntimeError):
        logging.exception("today advice failed telegram_id=%s", telegram_id)
        await callback.message.answer("I could not prepare your weather advice. Use /start or /reset if needed.")
        return

    await callback.message.answer(message)


@dp.callback_query(F.data == "menu:tomorrow")
async def handle_tomorrow_menu(callback: CallbackQuery) -> None:
    await callback.answer()

    telegram_id = callback.from_user.id

    try:
        result = await asyncio.to_thread(get_weather_for_user_from_db_or_fetch, telegram_id)
        context = build_weather_context(
            result["weather_json"],
            result["preferences"],
            result["location"],
            day="tomorrow",
        )
        message = await asyncio.to_thread(generate_ai_advice, context)
    except httpx.HTTPError:
        logging.exception("weather advice request failed telegram_id=%s", telegram_id)
        await callback.message.answer("I could not prepare the advice right now. Please try again later.")
        return
    except (psycopg.Error, RuntimeError):
        logging.exception("tomorrow advice failed telegram_id=%s", telegram_id)
        await callback.message.answer("I could not prepare your weather advice. Use /start or /reset if needed.")
        return

    await callback.message.answer(message)


@dp.callback_query(F.data == "menu:preferences")
async def handle_preferences_menu(callback: CallbackQuery) -> None:
    await callback.answer()

    telegram_id = callback.from_user.id

    try:
        preferences = await asyncio.to_thread(
            get_location_preferences_for_telegram_id,
            telegram_id,
        )
    except psycopg.Error:
        logging.exception("preferences menu failed telegram_id=%s", telegram_id)
        await callback.message.answer("I could not load your preferences. Please try again later.")
        return

    if not preferences:
        await callback.message.answer("No preferences found. Use /start to set up ANW.")
        return

    quiet_hours = "Off"
    if preferences.get("quiet_hours_enabled"):
        quiet_hours = f"{preferences.get('quiet_hours_start')} - {preferences.get('quiet_hours_end')}"

    text = "\n".join(
        [
            "Your preferences:",
            "",
            f"Location: {preferences.get('postal_code')} {preferences.get('city')}",
            f"Morning advice: {preferences.get('morning_time')}",
            f"Tomorrow advice: {preferences.get('evening_time')}",
            f"Quiet hours: {quiet_hours}",
            f"Cold sensitivity: {preferences.get('cold_sensitivity')}",
            f"Heat sensitivity: {preferences.get('heat_sensitivity')}",
            f"Bad weather sensitivity: {preferences.get('bad_weather_sensitivity')}",
            f"Advice type: {preferences.get('recommendation_style')}",
            f"Tone: {preferences.get('tone')}",
            f"Weather changes: {preferences.get('daytime_alerts')}",
            "",
            "To change preferences, use /reset.",
        ]
    )

    await callback.message.answer(text)

@dp.callback_query(F.data == "menu:quick_requests")
async def handle_quick_requests_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("Quick requests will be added soon.")


@dp.message(
    ~CommandStart(),
    ~Command("reset"),
    lambda message: message.from_user and message.from_user.id not in onboarding_sessions,
)
async def handle_other_messages(message: Message) -> None:
    """Fallback handler when onboarding is complete or not started."""
    user = message.from_user

    if user is None:
        return

    try:
        db_user = await asyncio.to_thread(upsert_user, user.id, user.username)
        saved_preferences = await asyncio.to_thread(get_saved_preferences, db_user["id"])
    except psycopg.Error:
        logging.exception("fallback user/preferences lookup failed telegram_id=%s", user.id)
        await message.answer("I could not load your preferences. Please try again later.")
        return

    if saved_preferences:
        await message.answer("Use the menu below, /start, or /reset.", reply_markup=main_menu_keyboard())
        return

    await message.answer("Use /start to set up ANW.")


async def main() -> None:
    await asyncio.to_thread(setup_database)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
