import asyncio
import logging
from typing import Any

import psycopg
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from database import (
    delete_preferences,
    get_saved_preferences,
    lookup_postal_code,
    save_preferences,
    upsert_user,
)
from keyboards import build_keyboard, main_menu_keyboard

logger = logging.getLogger(__name__)

router = Router()

# In-memory sessions. Good enough for MVP.
onboarding_sessions: dict[int, dict[str, Any]] = {}

_bot: Bot | None = None


def set_bot(bot: Bot) -> None:
    """Main file gives bot instance to onboarding module."""
    global _bot
    _bot = bot


def get_bot() -> Bot:
    if _bot is None:
        raise RuntimeError("Bot is not initialized.")
    return _bot


ONBOARDING_STEPS = [
    {
        "name": "Location",
        "question": "Please enter your Swiss postal code.\nExample: 8001",
        "type": "location",
    },
    {
        "name": "Morning advice",
        "field": "morning_time",
        "question": "When should I send your morning advice?",
        "buttons": [
            ("06:30", "06:30"),
            ("07:00", "07:00"),
            ("07:30", "07:30"),
            ("08:00", "08:00"),
        ],
    },
    {
        "name": "Tomorrow advice",
        "field": "evening_time",
        "question": "When should I send advice for tomorrow?",
        "buttons": [
            ("18:00", "18:00"),
            ("19:00", "19:00"),
            ("20:00", "20:00"),
            ("21:00", "21:00"),
        ],
    },
    {
        "name": "Quiet hours",
        "field": "quiet_hours",
        "question": "When should I not send messages?",
        "buttons": [
            ("22:00 - 07:00", "22_07"),
            ("23:00 - 06:00", "23_06"),
            ("Any time is OK", "none"),
        ],
    },
    {
        "name": "Cold weather",
        "field": "cold_sensitivity",
        "question": "Do you like cold weather?",
        "buttons": [
            ("No, I do not like it", "high"),
            ("It is OK", "medium"),
            ("Yes, I like it", "low"),
        ],
    },
    {
        "name": "Hot weather",
        "field": "heat_sensitivity",
        "question": "Do you like hot weather?",
        "buttons": [
            ("No, I do not like it", "high"),
            ("It is OK", "medium"),
            ("Yes, I like it", "low"),
        ],
    },
    {
        "name": "Rain, snow, and wind",
        "field": "bad_weather_sensitivity",
        "question": "Do you like rain, snow, and wind?",
        "buttons": [
            ("No, I do not like it", "high"),
            ("It is OK", "medium"),
            ("Yes, I like it", "low"),
        ],
    },
    {
        "name": "Advice type",
        "field": "recommendation_style",
        "question": "What kind of advice do you want?",
        "buttons": [
            ("Only tips", "practical"),
            ("Tips and ideas", "activities"),
            ("Tips and fun", "cozy_fun"),
        ],
    },
    {
        "name": "Tone",
        "field": "tone",
        "question": "How should I talk to you?",
        "buttons": [
            ("Formal", "formal"),
            ("Simple", "casual"),
            ("Funny", "humorous"),
        ],
    },
    {
        "name": "Weather changes",
        "field": "daytime_alerts",
        "question": "When should I tell you about weather changes?",
        "buttons": [
            ("All updates", "all"),
            ("Important only", "important"),
            ("Only morning and evening", "none"),
        ],
    },
]

TOTAL_ONBOARDING_STEPS = len(ONBOARDING_STEPS)

QUIET_HOURS_VALUES = {
    "22_07": {
        "quiet_hours_enabled": True,
        "quiet_hours_start": "22:00",
        "quiet_hours_end": "07:00",
    },
    "23_06": {
        "quiet_hours_enabled": True,
        "quiet_hours_start": "23:00",
        "quiet_hours_end": "06:00",
    },
    "none": {
        "quiet_hours_enabled": False,
        "quiet_hours_start": None,
        "quiet_hours_end": None,
    },
}


def telegram_user_data(message_or_callback: Message | CallbackQuery) -> tuple[int, str | None]:
    user = message_or_callback.from_user
    return user.id, user.username


async def ensure_user(message: Message) -> dict[str, Any] | None:
    telegram_id, username = telegram_user_data(message)

    try:
        return await asyncio.to_thread(upsert_user, telegram_id, username)
    except (psycopg.Error, RuntimeError):
        logger.exception("user upsert failed telegram_id=%s", telegram_id)
        await message.answer("I could not connect to the database. Please try again later.")
        return None


def step_name(step: int) -> str:
    if 0 <= step < TOTAL_ONBOARDING_STEPS:
        return str(ONBOARDING_STEPS[step]["name"])
    return "Completed"


def step_header(step: int) -> str:
    return f"{step + 1}/{TOTAL_ONBOARDING_STEPS} {step_name(step)}"


def normalized_step_update(field: str, value: str) -> dict[str, Any]:
    if field == "quiet_hours":
        return QUIET_HOURS_VALUES[value]

    return {field: value}


async def start_onboarding_for_user(chat_id: int, user_id: int, username: str | None) -> None:
    onboarding_sessions[user_id] = {
        "step_index": 0,
        "draft": {},
        "message_id": None,
        "username": username,
        "chat_id": chat_id,
    }

    await send_current_question(chat_id, user_id)


async def start_onboarding(message: Message) -> None:
    """Start clean onboarding session."""
    await start_onboarding_for_user(
        message.chat.id,
        message.from_user.id,
        message.from_user.username,
    )


async def send_current_question(chat_id: int, user_id: int) -> None:
    """Show one onboarding question.

    Important:
    We edit the same message instead of sending many messages.
    This prevents old buttons from breaking the flow.
    """
    session = onboarding_sessions.get(user_id)

    if not session:
        return

    step_index = int(session["step_index"])

    if step_index >= TOTAL_ONBOARDING_STEPS:
        return

    step = ONBOARDING_STEPS[step_index]
    draft = session["draft"]

    header = step_header(step_index)
    reply_markup = None

    if step_index == 0:
        locations = draft.get("pending_locations") or []

        if locations and not draft.get("pending_postal_code_id"):
            text = (
                f"{header}\n\n"
                f"I found several places for {draft.get('pending_postal_code')}.\n"
                "Please choose your city."
            )
            reply_markup = build_keyboard(
                [
                    (str(location["city"]), f"onboarding:location_select:{index}")
                    for index, location in enumerate(locations)
                ]
            )

        elif draft.get("pending_postal_code_id"):
            text = (
                f"{header}\n\n"
                f"{draft.get('pending_postal_code')} -> {draft.get('pending_city')}\n"
                "Is this correct?"
            )
            reply_markup = build_keyboard(
                [
                    ("Yes", "onboarding:location:yes"),
                    ("Change", "onboarding:location:change"),
                ]
            )

        else:
            text = f"{header}\n\n{step['question']}"

    else:
        text = f"{header}\n\n{step['question']}"
        reply_markup = build_keyboard(
            [
                (label, f"onboarding:{step['field']}:{value}")
                for label, value in step["buttons"]
            ]
        )

    bot = get_bot()
    message_id = session.get("message_id")

    if message_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            logger.exception("Could not edit onboarding message. Sending new one.")

    sent = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
    )

    session["message_id"] = sent.message_id


async def handle_onboarding_answer(
    message_or_callback: Message | CallbackQuery,
    user_id: int,
    answer: str,
) -> None:
    """Main onboarding answer handler.

    This keeps onboarding linear:
    current step -> validate answer -> save answer -> next step.
    """
    session = onboarding_sessions.get(user_id)

    if not session:
        return

    step_index = int(session["step_index"])
    draft = session["draft"]
    chat_id = session.get("chat_id", user_id)

    if step_index == 0:
        await handle_location_step(chat_id, user_id, answer, draft, session)
        return

    step = ONBOARDING_STEPS[step_index]
    field = str(step["field"])
    valid_values = {button_value for _, button_value in step["buttons"]}

    if answer not in valid_values:
        await send_current_question(chat_id, user_id)
        return

    draft.update(normalized_step_update(field, answer))
    session["step_index"] = step_index + 1

    if session["step_index"] >= TOTAL_ONBOARDING_STEPS:
        await finish_onboarding(user_id)
        return

    await send_current_question(chat_id, user_id)


async def handle_location_step(
    chat_id: int,
    user_id: int,
    answer: str,
    draft: dict[str, Any],
    session: dict[str, Any],
) -> None:
    """Special handling for postal code and city choice."""
    bot = get_bot()

    if answer == "location:change":
        draft.clear()
        await send_current_question(chat_id, user_id)
        return

    if answer == "location:yes":
        postal_code_id = draft.get("pending_postal_code_id")

        if not postal_code_id:
            await send_current_question(chat_id, user_id)
            return

        draft["postal_code_id"] = postal_code_id
        session["step_index"] = 1

        await send_current_question(chat_id, user_id)
        return

    if answer.startswith("location_select:"):
        locations = draft.get("pending_locations") or []

        try:
            location_index = int(answer.split(":", maxsplit=1)[1])
            location = locations[location_index]
        except (ValueError, IndexError, TypeError):
            await send_current_question(chat_id, user_id)
            return

        draft["pending_postal_code"] = location["postal_code"]
        draft["pending_postal_code_id"] = location["id"]
        draft["pending_city"] = location["city"]

        await send_current_question(chat_id, user_id)
        return

    postal_code = answer.strip()

    if not (postal_code.isdigit() and len(postal_code) == 4):
        await bot.send_message(chat_id, "Please enter exactly 4 digits.")
        await send_current_question(chat_id, user_id)
        return

    try:
        locations = await asyncio.to_thread(lookup_postal_code, postal_code)
    except psycopg.Error:
        logger.exception("postal code lookup failed user_id=%s postal_code=%s", user_id, postal_code)
        await bot.send_message(
            chat_id,
            "I could not look up postal codes right now. Please try again later.",
        )
        return

    if not locations:
        await bot.send_message(chat_id, "I could not find this Swiss postal code. Please try again.")
        await send_current_question(chat_id, user_id)
        return

    draft["pending_postal_code"] = postal_code
    draft["pending_locations"] = locations
    draft["pending_postal_code_id"] = None
    draft["pending_city"] = None

    if len(locations) == 1:
        location = locations[0]
        draft["pending_postal_code_id"] = location["id"]
        draft["pending_city"] = location["city"]

    await send_current_question(chat_id, user_id)


async def finish_onboarding(user_id: int) -> None:
    """Save final preferences and show main menu."""
    session = onboarding_sessions.get(user_id)

    if not session:
        return

    bot = get_bot()
    draft = session["draft"]
    username = session.get("username")
    chat_id = session.get("chat_id", user_id)

    try:
        await asyncio.to_thread(save_preferences, user_id, username, draft)
    except (psycopg.Error, RuntimeError):
        logger.exception("preferences save failed telegram_id=%s", user_id)
        await bot.send_message(chat_id, "I could not save your settings. Please try again later.")
        return

    onboarding_sessions.pop(user_id, None)

    await bot.send_message(
        chat_id,
        "Settings saved.",
        reply_markup=main_menu_keyboard(),
    )


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    user = await ensure_user(message)

    if user is None:
        return

    try:
        saved_preferences = await asyncio.to_thread(get_saved_preferences, user["id"])
    except psycopg.Error:
        logger.exception("preferences lookup failed user_id=%s", user["id"])
        await message.answer("I could not load your settings. Please try again later.")
        return

    if saved_preferences:
        onboarding_sessions.pop(message.from_user.id, None)
        await message.answer("Your settings are ready.", reply_markup=main_menu_keyboard())
        return

    await start_onboarding(message)


@router.message(Command("reset"))
async def handle_reset(message: Message) -> None:
    user = await ensure_user(message)

    if user is None:
        return

    try:
        await asyncio.to_thread(delete_preferences, user["id"])
    except psycopg.Error:
        logger.exception("preferences delete failed user_id=%s", user["id"])
        await message.answer("I could not change your settings. Please try again later.")
        return

    onboarding_sessions.pop(message.from_user.id, None)

    await message.answer("Let's change your settings.", reply_markup=ReplyKeyboardRemove())
    await start_onboarding(message)


@router.callback_query(F.data.startswith("onboarding:"))
async def handle_onboarding_callback(callback: CallbackQuery) -> None:
    await callback.answer()

    user_id = callback.from_user.id
    callback_data = callback.data or ""

    session = onboarding_sessions.get(user_id)

    if session is None:
        return

    parts = callback_data.split(":")

    if len(parts) < 3:
        await send_current_question(session.get("chat_id", user_id), user_id)
        return

    field = parts[1]
    value = ":".join(parts[2:])
    step_index = int(session["step_index"])

    if step_index == 0 and field in {"location", "location_select"}:
        await handle_onboarding_answer(callback, user_id, f"{field}:{value}")
        return

    if step_index <= 0 or step_index >= TOTAL_ONBOARDING_STEPS:
        await send_current_question(session.get("chat_id", user_id), user_id)
        return

    current_step = ONBOARDING_STEPS[step_index]

    # Ignore old buttons from old steps.
    if field != current_step.get("field"):
        await send_current_question(session.get("chat_id", user_id), user_id)
        return

    await handle_onboarding_answer(callback, user_id, value)


@router.message(lambda message: message.from_user and message.from_user.id in onboarding_sessions)
async def handle_onboarding_text(message: Message) -> None:
    """Only postal code should normally come here."""
    user_id = message.from_user.id

    try:
        await message.delete()
    except Exception:
        pass

    await handle_onboarding_answer(message, user_id, message.text or "")
