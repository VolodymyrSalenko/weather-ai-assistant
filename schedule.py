import asyncio
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot

from ai_advice import generate_ai_advice
from config import BOT_TOKEN, ZURICH_TZ
from database import (
    cleanup_old_weather_forecasts,
    get_active_postal_code_locations,
    get_all_postal_code_locations,
    get_completed_preferences_for_postal_code,
    get_completed_preferences_for_notifications,
    get_latest_stored_weather_forecast,
    has_notification_been_sent,
    log_notification_sent,
    mark_notification_sent,
    setup_database,
)
from weather import (
    build_weather_context,
    fetch_and_store_weather_for_location,
    get_weather_for_user_from_db_or_fetch,
)
from weather_changes import detect_weather_changes


ACTIVE_UPDATE_SECONDS = 2 * 60 * 60
NOTIFICATION_CHECK_SECONDS = 60
FULL_UPDATE_HOUR = 3
WEATHER_CHANGE_NOTIFICATION_TYPE = "weather_change_today"


def location_label(location: dict[str, Any]) -> str:
    postal_code = location.get("postal_code") or "unknown postal code"
    city = location.get("city") or "unknown city"
    return f"{postal_code} {city}"


def advice_header(context: dict[str, Any], day: str) -> str:
    target_date = datetime.now(ZURICH_TZ).date()
    label = "Today"

    if day == "tomorrow":
        target_date += timedelta(days=1)
        label = "Tomorrow"

    city = str(context.get("location") or "Your location").upper()
    date_text = f"{target_date.strftime('%a')}, {target_date.day} {target_date.strftime('%b')}"
    return f"{city}\n{label} · {date_text}"


def time_minutes(value: Any) -> int | None:
    if value is None:
        return None

    try:
        hour, minute = str(value)[:5].split(":")
        return int(hour) * 60 + int(minute)
    except ValueError:
        return None


def time_matches_current_minute(value: Any, now: datetime) -> bool:
    return time_minutes(value) == now.hour * 60 + now.minute


def is_quiet_time(preferences: dict[str, Any], now: datetime) -> bool:
    if not preferences.get("quiet_hours_enabled"):
        return False

    start = time_minutes(preferences.get("quiet_hours_start"))
    end = time_minutes(preferences.get("quiet_hours_end"))

    if start is None or end is None:
        return False

    current = now.hour * 60 + now.minute

    if start == end:
        return True

    if start < end:
        return start <= current < end

    return current >= start or current < end


async def update_weather_for_locations(locations: list[dict[str, Any]]) -> None:
    for location in locations:
        try:
            forecast_id = await asyncio.to_thread(fetch_and_store_weather_for_location, location)
            print(f"Updated weather for {location_label(location)} forecast_id={forecast_id}")
        except Exception as error:
            print(f"Weather update failed for {location_label(location)}: {error}")


async def send_weather_change_alerts(
    bot: Bot,
    location: dict[str, Any],
    new_weather_json: dict[str, Any],
    weather_changes: dict[str, Any],
) -> None:
    now = datetime.now(ZURICH_TZ)
    preferences_rows = await asyncio.to_thread(
        get_completed_preferences_for_postal_code,
        int(location["id"]),
    )

    for preferences in preferences_rows:
        if preferences.get("daytime_alerts") == "none":
            continue

        if is_quiet_time(preferences, now):
            continue

        already_sent = await asyncio.to_thread(
            has_notification_been_sent,
            int(preferences["user_id"]),
            WEATHER_CHANGE_NOTIFICATION_TYPE,
            now.date(),
        )

        if already_sent:
            continue

        context = build_weather_context(new_weather_json, preferences, location, day="today")
        context["weather_changes"] = weather_changes

        try:
            message = await asyncio.to_thread(generate_ai_advice, context)
        except Exception as error:
            print(f"Weather change AI advice failed for {location_label(location)}: {error}")
            continue

        logged = await asyncio.to_thread(
            log_notification_sent,
            int(preferences["user_id"]),
            WEATHER_CHANGE_NOTIFICATION_TYPE,
            now.date(),
        )

        if not logged:
            continue

        try:
            await bot.send_message(
                int(preferences["telegram_id"]),
                f"{advice_header(context, 'today')}\n\n{message}",
            )
            print(f"Sent weather change alert to telegram_id={preferences['telegram_id']}")
        except Exception as error:
            print(f"Weather change alert failed for telegram_id={preferences['telegram_id']}: {error}")


async def update_active_weather_for_locations(locations: list[dict[str, Any]], bot: Bot | None = None) -> None:
    for location in locations:
        try:
            old_weather_json = await asyncio.to_thread(
                get_latest_stored_weather_forecast,
                int(location["id"]),
            )
            forecast_id = await asyncio.to_thread(fetch_and_store_weather_for_location, location)
            print(f"Updated weather for {location_label(location)} forecast_id={forecast_id}")

            if old_weather_json is None:
                print("No previous forecast to compare")
                continue

            new_weather_json = await asyncio.to_thread(
                get_latest_stored_weather_forecast,
                int(location["id"]),
            )

            if new_weather_json is None:
                continue

            result = detect_weather_changes(old_weather_json, new_weather_json, day="today")

            if result["important_change"]:
                print(f"Today changes for {location_label(location)}: {', '.join(result['changes'])}")
                if bot is not None:
                    await send_weather_change_alerts(bot, location, new_weather_json, result)
        except Exception as error:
            print(f"Weather update failed for {location_label(location)}: {error}")


async def cleanup_weather_forecasts() -> None:
    print("Running weather forecast cleanup.")
    await asyncio.to_thread(cleanup_old_weather_forecasts, days=14)


async def update_active_locations(bot: Bot | None = None) -> None:
    print("Starting active weather update.")
    locations = await asyncio.to_thread(get_active_postal_code_locations)
    print(f"Found {len(locations)} active locations.")
    await update_active_weather_for_locations(locations, bot)
    await cleanup_weather_forecasts()


async def update_all_locations() -> None:
    print("Starting full daily weather update.")
    locations = await asyncio.to_thread(get_all_postal_code_locations)
    print(f"Found {len(locations)} postal code locations.")
    await update_weather_for_locations(locations)
    await cleanup_weather_forecasts()


async def active_locations_loop(bot: Bot) -> None:
    print("Active weather update interval is 2 hours.")

    while True:
        await asyncio.sleep(ACTIVE_UPDATE_SECONDS)
        await update_active_locations(bot)


def next_full_update_time() -> datetime:
    now = datetime.now(ZURICH_TZ)
    next_update = now.replace(hour=FULL_UPDATE_HOUR, minute=0, second=0, microsecond=0)

    if next_update <= now:
        next_update += timedelta(days=1)

    return next_update


async def all_locations_loop() -> None:
    while True:
        next_update = next_full_update_time()
        print(f"Next full weather update: {next_update.strftime('%Y-%m-%d %H:%M %Z')}")
        await asyncio.sleep((next_update - datetime.now(ZURICH_TZ)).total_seconds())
        await update_all_locations()


async def send_scheduled_advice(
    bot: Bot,
    preferences: dict[str, Any],
    notification_type: str,
    day: str,
    now: datetime,
) -> None:
    logged = await asyncio.to_thread(
        mark_notification_sent,
        int(preferences["user_id"]),
        notification_type,
        now.date(),
    )

    if not logged:
        return

    telegram_id = int(preferences["telegram_id"])

    try:
        result = await asyncio.to_thread(get_weather_for_user_from_db_or_fetch, telegram_id)
        context = build_weather_context(
            result["weather_json"],
            result["preferences"],
            result["location"],
            day=day,
        )
        message = await asyncio.to_thread(generate_ai_advice, context)
        await bot.send_message(telegram_id, f"{advice_header(context, day)}\n\n{message}")
        print(f"Sent {notification_type} advice to telegram_id={telegram_id}")
    except Exception as error:
        print(f"Scheduled {notification_type} advice failed for telegram_id={telegram_id}: {error}")


async def check_scheduled_notifications(bot: Bot) -> None:
    now = datetime.now(ZURICH_TZ)
    preferences_rows = await asyncio.to_thread(get_completed_preferences_for_notifications)

    for preferences in preferences_rows:
        if is_quiet_time(preferences, now):
            continue

        if time_matches_current_minute(preferences.get("morning_time"), now):
            await send_scheduled_advice(bot, preferences, "morning", "today", now)

        if time_matches_current_minute(preferences.get("evening_time"), now):
            await send_scheduled_advice(bot, preferences, "evening", "tomorrow", now)


async def notification_loop(bot: Bot) -> None:
    while True:
        try:
            await check_scheduled_notifications(bot)
        except Exception as error:
            print(f"Scheduled notification check failed: {error}")
        await asyncio.sleep(NOTIFICATION_CHECK_SECONDS)


async def main() -> None:
    await asyncio.to_thread(setup_database)
    bot = Bot(token=BOT_TOKEN)
    await update_active_locations(bot)

    try:
        await asyncio.gather(active_locations_loop(bot), all_locations_loop(), notification_loop(bot))
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
