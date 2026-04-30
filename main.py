import asyncio
import logging
from datetime import datetime, timedelta

import httpx
import psycopg
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from ai_advice import generate_ai_advice
from config import BOT_TOKEN, ZURICH_TZ
from database import (
    delete_preferences,
    get_location_preferences_for_telegram_id,
    get_saved_preferences,
    setup_database,
    upsert_user,
)
from keyboards import ASK_QUESTIONS, ask_questions_keyboard, change_settings_keyboard, main_menu_keyboard
from onboarding import onboarding_sessions
from onboarding import router as onboarding_router
from onboarding import set_bot, start_onboarding_for_user
from weather import build_weather_context, get_weather_for_user_from_db_or_fetch

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

set_bot(bot)
dp.include_router(onboarding_router)


def is_not_onboarding(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id not in onboarding_sessions)


def advice_header(context: dict, day: str) -> str:
    target_date = datetime.now(ZURICH_TZ).date()
    label = "Today"

    if day == "tomorrow":
        target_date += timedelta(days=1)
        label = "Tomorrow"

    city = str(context.get("location") or "Your location").upper()
    date_text = f"{target_date.strftime('%a')}, {target_date.day} {target_date.strftime('%b')}"
    return f"{city}\n{label} · {date_text}"


async def build_weather_advice_message(telegram_id: int, day: str) -> str:
    result = await asyncio.to_thread(get_weather_for_user_from_db_or_fetch, telegram_id)
    context = build_weather_context(
        result["weather_json"],
        result["preferences"],
        result["location"],
        day=day,
    )
    advice = await asyncio.to_thread(generate_ai_advice, context)
    return f"{advice_header(context, day)}\n\n{advice}"


async def send_weather_advice(message: Message, telegram_id: int, day: str) -> None:
    try:
        advice = await build_weather_advice_message(telegram_id, day)
    except httpx.HTTPError:
        logging.exception("weather advice request failed telegram_id=%s", telegram_id)
        await message.answer("I could not prepare the advice right now. Please try again later.")
        return
    except (psycopg.Error, RuntimeError):
        logging.exception("%s advice failed telegram_id=%s", day, telegram_id)
        await message.answer("I could not prepare your weather advice. Use /start or change settings if needed.")
        return

    await message.answer(advice)


async def send_settings(message: Message, telegram_id: int) -> None:
    try:
        preferences = await asyncio.to_thread(
            get_location_preferences_for_telegram_id,
            telegram_id,
        )
    except psycopg.Error:
        logging.exception("settings menu failed telegram_id=%s", telegram_id)
        await message.answer("I could not load your settings. Please try again later.")
        return

    if not preferences:
        await message.answer("No settings found. Use /start to set up ANW.")
        return

    quiet_hours = "Off"
    if preferences.get("quiet_hours_enabled"):
        quiet_hours = f"{preferences.get('quiet_hours_start')} - {preferences.get('quiet_hours_end')}"

    text = "\n".join(
        [
            "Your settings:",
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
            "To change settings, use the button below.",
        ]
    )

    await message.answer(text, reply_markup=change_settings_keyboard())


@dp.callback_query(F.data == "menu:today")
async def handle_today_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await send_weather_advice(callback.message, callback.from_user.id, "today")


@dp.message(F.text == "Today", is_not_onboarding)
async def handle_today_button(message: Message) -> None:
    await send_weather_advice(message, message.from_user.id, "today")


@dp.callback_query(F.data == "menu:tomorrow")
async def handle_tomorrow_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await send_weather_advice(callback.message, callback.from_user.id, "tomorrow")


@dp.message(F.text == "Tomorrow", is_not_onboarding)
async def handle_tomorrow_button(message: Message) -> None:
    await send_weather_advice(message, message.from_user.id, "tomorrow")


@dp.callback_query(F.data == "menu:preferences")
async def handle_preferences_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await send_settings(callback.message, callback.from_user.id)


@dp.message(F.text == "Settings", is_not_onboarding)
async def handle_settings_button(message: Message) -> None:
    await send_settings(message, message.from_user.id)


@dp.callback_query(F.data == "settings:change")
async def handle_change_settings(callback: CallbackQuery) -> None:
    await callback.answer()

    user_id = callback.from_user.id
    username = callback.from_user.username
    chat_id = callback.message.chat.id

    try:
        user = await asyncio.to_thread(upsert_user, user_id, username)
        await asyncio.to_thread(delete_preferences, user["id"])
    except psycopg.Error:
        logging.exception("settings change failed telegram_id=%s", user_id)
        await callback.message.answer("I could not change your settings. Please try again later.")
        return

    onboarding_sessions.pop(user_id, None)
    await callback.message.answer("Let's change your settings.", reply_markup=ReplyKeyboardRemove())
    await start_onboarding_for_user(chat_id, user_id, username)


@dp.callback_query(F.data == "menu:quick_requests")
async def handle_quick_requests_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "Choose a question or write your own.",
        reply_markup=ask_questions_keyboard(),
    )


@dp.message(F.text == "Ask", is_not_onboarding)
async def handle_ask_button(message: Message) -> None:
    await message.answer(
        "Choose a question or write your own.",
        reply_markup=ask_questions_keyboard(),
    )


@dp.callback_query(F.data.startswith("ask:"))
async def handle_ask_question(callback: CallbackQuery) -> None:
    await callback.answer()

    try:
        question = ASK_QUESTIONS[int((callback.data or "").split(":", maxsplit=1)[1])]
    except (IndexError, ValueError):
        return

    await callback.message.answer(f"You selected: {question}")


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
        await message.answer("I could not load your settings. Please try again later.")
        return

    if saved_preferences:
        await message.answer("Use the menu below.", reply_markup=main_menu_keyboard())
        return

    await message.answer("Use /start to set up ANW.")


async def main() -> None:
    await asyncio.to_thread(setup_database)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
