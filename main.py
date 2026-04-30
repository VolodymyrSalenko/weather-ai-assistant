import asyncio
import logging
from datetime import date, datetime, timedelta

import httpx
import psycopg
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from ai_advice import generate_ai_advice
from ai_chat import NON_WEATHER_REPLY, generate_weather_chat_answer, understand_weather_question
from config import BOT_TOKEN, ZURICH_TZ
from database import (
    delete_preferences,
    find_postal_code_location,
    get_latest_stored_weather_forecast,
    get_location_preferences_for_telegram_id,
    get_saved_preferences,
    setup_database,
    upsert_user,
)
from keyboards import ASK_QUESTIONS, ask_questions_keyboard, change_settings_keyboard
from onboarding import onboarding_sessions
from onboarding import router as onboarding_router
from onboarding import set_bot, start_onboarding_for_user
from weather import (
    build_weather_context,
    build_weather_period_context,
    fetch_and_store_weather_for_location,
    get_weather_for_user_from_db_or_fetch,
)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_states = {}

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


def short_date(forecast_date: date) -> str:
    return f"{forecast_date.strftime('%a')}, {forecast_date.day} {forecast_date.strftime('%b')}"


def single_day_period(period_type: str, target_date: date, label: str) -> dict:
    return {
        "type": period_type,
        "date": target_date.isoformat(),
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "label": label,
    }


def parse_day_reply(text: str) -> dict | None:
    today = datetime.now(ZURICH_TZ).date()
    normalized = text.strip().lower()

    if not normalized:
        return None

    if "day after tomorrow" in normalized or "after tomorrow" in normalized:
        return single_day_period("day_after_tomorrow", today + timedelta(days=2), "Day after tomorrow")

    if "tomorrow" in normalized:
        return single_day_period("tomorrow", today + timedelta(days=1), "Tomorrow")

    if "today" in normalized:
        return single_day_period("today", today, "Today")

    if "weekend" in normalized:
        saturday = today + timedelta(days=(5 - today.weekday()) % 7)
        sunday = saturday + timedelta(days=1)
        return {
            "type": "weekend",
            "date": None,
            "start_date": saturday.isoformat(),
            "end_date": sunday.isoformat(),
            "label": "Weekend",
        }

    if "week" in normalized:
        return {
            "type": "week",
            "date": None,
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=6)).isoformat(),
            "label": "This week",
        }

    try:
        target_date = date.fromisoformat(normalized)
        return single_day_period("specific_date", target_date, target_date.strftime("%A"))
    except ValueError:
        pass

    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    for weekday_name, weekday_index in weekdays.items():
        if weekday_name in normalized:
            days_until = (weekday_index - today.weekday()) % 7
            target_date = today + timedelta(days=days_until)
            return single_day_period("specific_date", target_date, target_date.strftime("%A"))

    return None


def chat_answer_header(context: dict) -> str:
    city = str(context.get("location") or "Your location").upper()
    label = context.get("period_label") or "Today"
    start_date = date.fromisoformat(context["start_date"])
    end_date = date.fromisoformat(context["end_date"])

    if start_date == end_date:
        return f"{city}\n{label} · {short_date(start_date)}"

    return f"{city}\n{label} · {short_date(start_date)} - {short_date(end_date)}"


def missing_field_from_intent(intent: dict) -> str | None:
    question = str(intent.get("clarifying_question") or "").lower()

    if (intent.get("time_period") or {}).get("type") == "unknown":
        return "day"

    if any(word in question for word in ("city", "location", "where", "postal code")):
        return "location"

    if any(word in question for word in ("day", "date", "when")):
        return "day"

    if not intent.get("location") and not intent.get("use_saved_location"):
        return "location"

    return None


async def merge_pending_intent(user_id: int, user_text: str) -> dict | None:
    state = user_states.get(user_id)

    if not state or not state.get("waiting_for"):
        return None

    waiting_for = state["waiting_for"]
    intent = dict(state["pending_intent"])

    if waiting_for == "location":
        location = await asyncio.to_thread(find_postal_code_location, user_text.strip())

        if location is None:
            user_states.pop(user_id, None)
            return None

        intent["location"] = user_text.strip()
        intent["use_saved_location"] = False
        intent["cleaned_question"] = str(intent.get("cleaned_question") or "").replace("[city]", user_text.strip())

    elif waiting_for == "day":
        period = parse_day_reply(user_text)

        if period is None:
            user_states.pop(user_id, None)
            return None

        intent["time_period"] = period
        intent["cleaned_question"] = str(intent.get("cleaned_question") or "").replace("[day]", user_text.strip())

    else:
        user_states.pop(user_id, None)
        return None

    if (intent.get("time_period") or {}).get("type") == "unknown":
        intent["needs_clarification"] = True
        intent["clarifying_question"] = "Which day should I check?"
    elif not intent.get("location") and not intent.get("use_saved_location"):
        intent["needs_clarification"] = True
        intent["clarifying_question"] = "Which city should I check?"
    else:
        intent["needs_clarification"] = False
        intent["clarifying_question"] = None

    user_states.pop(user_id, None)
    return intent


def saved_location_from_preferences(preferences: dict) -> dict:
    return {
        "id": preferences.get("postal_code_id"),
        "postal_code_id": preferences.get("postal_code_id"),
        "postal_code": preferences.get("postal_code"),
        "city": preferences.get("city"),
        "canton": preferences.get("canton"),
        "latitude": preferences.get("latitude"),
        "longitude": preferences.get("longitude"),
    }


async def load_weather_for_location(location: dict) -> dict:
    postal_code_id = int(location.get("id") or location.get("postal_code_id"))
    weather_json = await asyncio.to_thread(get_latest_stored_weather_forecast, postal_code_id)

    if weather_json is None:
        await asyncio.to_thread(fetch_and_store_weather_for_location, location)
        weather_json = await asyncio.to_thread(get_latest_stored_weather_forecast, postal_code_id)

    if weather_json is None:
        raise RuntimeError("Could not load weather forecast.")

    return weather_json


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


async def answer_weather_question(message: Message, telegram_id: int, user_text: str) -> None:
    intent = await merge_pending_intent(telegram_id, user_text)

    if intent is None:
        try:
            intent = await asyncio.to_thread(understand_weather_question, user_text)
        except httpx.HTTPError:
            logging.exception("weather question intent failed telegram_id=%s", telegram_id)
            await message.answer("I could not understand that right now. Please try again later.")
            return
        except (RuntimeError, ValueError):
            logging.exception("weather question setup failed telegram_id=%s", telegram_id)
            await message.answer("I could not answer that right now. Please try again later.")
            return

    if not intent.get("is_weather_related"):
        user_states.pop(telegram_id, None)
        await message.answer(intent.get("reply") or NON_WEATHER_REPLY)
        return

    if intent.get("needs_clarification"):
        waiting_for = missing_field_from_intent(intent)

        if waiting_for and intent.get("clarifying_question"):
            user_states[telegram_id] = {
                "pending_intent": intent,
                "waiting_for": waiting_for,
            }

        await message.answer(intent.get("clarifying_question") or "Can you tell me a little more?")
        return

    user_states.pop(telegram_id, None)

    try:
        preferences = await asyncio.to_thread(get_location_preferences_for_telegram_id, telegram_id)
    except psycopg.Error:
        logging.exception("weather question preferences failed telegram_id=%s", telegram_id)
        await message.answer("I could not load your settings. Please try again later.")
        return

    if preferences is None:
        await message.answer("Use /start to set up ANW.")
        return

    if intent.get("location"):
        location = await asyncio.to_thread(find_postal_code_location, str(intent["location"]))

        if location is None:
            await message.answer("I could not find that place. Try another Swiss city or postal code.")
            return
    else:
        location = saved_location_from_preferences(preferences)

    try:
        weather_json = await load_weather_for_location(location)
    except (psycopg.Error, RuntimeError):
        logging.exception("weather question forecast failed telegram_id=%s", telegram_id)
        await message.answer("I could not load the weather right now. Please try again later.")
        return

    context = build_weather_period_context(
        weather_json,
        preferences,
        location,
        intent.get("time_period") or {},
    )
    context["user_question"] = intent.get("cleaned_question") or user_text
    context["question_type"] = intent.get("question_type")

    try:
        answer = await asyncio.to_thread(
            generate_weather_chat_answer,
            intent.get("cleaned_question") or user_text,
            context,
        )
    except httpx.HTTPError:
        logging.exception("weather question answer failed telegram_id=%s", telegram_id)
        await message.answer("I could not answer that right now. Please try again later.")
        return
    except RuntimeError:
        logging.exception("weather question setup failed telegram_id=%s", telegram_id)
        await message.answer("I could not answer that right now. Please try again later.")
        return

    await message.answer(f"{chat_answer_header(context)}\n\n{answer}")


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

    await answer_weather_question(callback.message, callback.from_user.id, question)


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
        await answer_weather_question(message, user.id, message.text or "")
        return

    await message.answer("Use /start to set up ANW.")


async def main() -> None:
    await asyncio.to_thread(setup_database)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
