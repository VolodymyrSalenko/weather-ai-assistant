import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from pprint import pformat
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import psycopg
from psycopg.types.json import Jsonb
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv


WELCOME_TEXT = "Welcome to ANW - Always Nice Weather."

CREATE_USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PREFERENCES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    postal_code_id INTEGER REFERENCES postal_codes(id),
    morning_time TIME,
    evening_time TIME,
    quiet_hours_enabled BOOLEAN DEFAULT TRUE,
    quiet_hours_start TIME,
    quiet_hours_end TIME,
    cold_sensitivity TEXT CHECK (cold_sensitivity IN ('high', 'medium', 'low')),
    heat_sensitivity TEXT CHECK (heat_sensitivity IN ('high', 'medium', 'low')),
    bad_weather_sensitivity TEXT CHECK (bad_weather_sensitivity IN ('high', 'medium', 'low')),
    recommendation_style TEXT CHECK (recommendation_style IN ('practical', 'activities', 'cozy_fun')),
    tone TEXT CHECK (tone IN ('formal', 'casual', 'humorous')),
    daytime_alerts TEXT CHECK (daytime_alerts IN ('all', 'important', 'none')),
    completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_WEATHER_FORECASTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS weather_forecasts (
    id SERIAL PRIMARY KEY,
    postal_code_id INTEGER REFERENCES postal_codes(id) ON DELETE CASCADE,
    source TEXT DEFAULT 'open_meteo',
    forecast_date DATE NOT NULL,
    forecast_type TEXT CHECK (forecast_type IN ('current', 'hourly', 'daily', 'full')),
    raw_json JSONB NOT NULL,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_WEATHER_FORECASTS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS weather_forecasts_lookup_idx
ON weather_forecasts (postal_code_id, forecast_date, fetched_at DESC);
"""

POSTAL_CODE_QUERY = """
SELECT id, postal_code, city, canton, latitude, longitude
FROM postal_codes
WHERE postal_code = %s
ORDER BY city;
"""

UPSERT_USER_SQL = """
INSERT INTO users (telegram_id, username, updated_at)
VALUES (%s, %s, CURRENT_TIMESTAMP)
ON CONFLICT (telegram_id) DO UPDATE
SET username = EXCLUDED.username,
    updated_at = CURRENT_TIMESTAMP
RETURNING id, telegram_id, username, created_at, updated_at;
"""

INSERT_PREFERENCES_SQL = """
INSERT INTO preferences (
    user_id,
    postal_code_id,
    morning_time,
    evening_time,
    quiet_hours_enabled,
    quiet_hours_start,
    quiet_hours_end,
    cold_sensitivity,
    heat_sensitivity,
    bad_weather_sensitivity,
    recommendation_style,
    tone,
    daytime_alerts,
    completed,
    updated_at
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
RETURNING id;
"""

SAVED_PREFERENCES_SQL = """
SELECT
    p.id,
    p.user_id,
    p.postal_code_id,
    pc.postal_code,
    pc.city,
    pc.canton,
    pc.latitude,
    pc.longitude,
    p.morning_time::text,
    p.evening_time::text,
    p.quiet_hours_enabled,
    p.quiet_hours_start::text,
    p.quiet_hours_end::text,
    p.cold_sensitivity,
    p.heat_sensitivity,
    p.bad_weather_sensitivity,
    p.recommendation_style,
    p.tone,
    p.daytime_alerts,
    p.completed,
    p.created_at,
    p.updated_at
FROM preferences p
LEFT JOIN postal_codes pc ON pc.id = p.postal_code_id
WHERE p.user_id = %s AND p.completed = TRUE
ORDER BY p.updated_at DESC
LIMIT 1;
"""

USER_LOCATION_PREFERENCES_SQL = """
SELECT
    p.id,
    p.user_id,
    p.postal_code_id,
    pc.postal_code,
    pc.city,
    pc.canton,
    pc.latitude,
    pc.longitude,
    p.morning_time::text,
    p.evening_time::text,
    p.quiet_hours_enabled,
    p.quiet_hours_start::text,
    p.quiet_hours_end::text,
    p.cold_sensitivity,
    p.heat_sensitivity,
    p.bad_weather_sensitivity,
    p.recommendation_style,
    p.tone,
    p.daytime_alerts,
    p.completed,
    p.created_at,
    p.updated_at
FROM users u
JOIN preferences p ON p.user_id = u.id
JOIN postal_codes pc ON pc.id = p.postal_code_id
WHERE u.telegram_id = %s AND p.completed = TRUE
ORDER BY p.updated_at DESC
LIMIT 1;
"""

INSERT_WEATHER_FORECAST_SQL = """
INSERT INTO weather_forecasts (
    postal_code_id,
    source,
    forecast_date,
    forecast_type,
    raw_json
)
VALUES (%s, 'open_meteo', %s, 'full', %s)
RETURNING id;
"""

LATEST_WEATHER_STATUS_SQL = """
SELECT
    wf.id,
    wf.forecast_date,
    wf.forecast_type,
    wf.fetched_at,
    pc.postal_code,
    pc.city
FROM preferences p
JOIN postal_codes pc ON pc.id = p.postal_code_id
LEFT JOIN weather_forecasts wf ON wf.id = (
    SELECT id
    FROM weather_forecasts
    WHERE postal_code_id = p.postal_code_id
      AND source = 'open_meteo'
      AND forecast_type = 'full'
    ORDER BY fetched_at DESC
    LIMIT 1
)
WHERE p.user_id = %s AND p.completed = TRUE
ORDER BY p.updated_at DESC
LIMIT 1;
"""

Location = dict[str, Any]
ZURICH_TZ = ZoneInfo("Europe/Zurich")
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

logger = logging.getLogger(__name__)
dp = Dispatcher()


class Onboarding(StatesGroup):
    postal_code = State()
    postal_city = State()
    postal_confirm = State()
    morning_time = State()
    evening_time = State()
    quiet_hours = State()
    cold_sensitivity = State()
    heat_sensitivity = State()
    bad_weather_sensitivity = State()
    recommendation_style = State()
    tone = State()
    daytime_alerts = State()


STEP_CONFIGS = [
    {
        "state": Onboarding.morning_time,
        "field": "morning_time",
        "question": "When should I send your morning advice?",
        "buttons": [
            ("06:30", "06:30"),
            ("07:00", "07:00"),
            ("07:30", "07:30"),
            ("08:00", "08:00"),
        ],
        "next_state": Onboarding.evening_time,
    },
    {
        "state": Onboarding.evening_time,
        "field": "evening_time",
        "question": "When should I send advice for tomorrow?",
        "buttons": [
            ("18:00", "18:00"),
            ("19:00", "19:00"),
            ("20:00", "20:00"),
            ("21:00", "21:00"),
        ],
        "next_state": Onboarding.quiet_hours,
    },
    {
        "state": Onboarding.quiet_hours,
        "field": "quiet_hours",
        "question": "When should I not send messages?",
        "buttons": [
            ("22:00 – 07:00", "22_07"),
            ("23:00 – 06:00", "23_06"),
            ("Any time is OK", "none"),
        ],
        "next_state": Onboarding.cold_sensitivity,
    },
    {
        "state": Onboarding.cold_sensitivity,
        "field": "cold_sensitivity",
        "question": "Do you like cold weather?",
        "buttons": [
            ("No, I do not like it", "high"),
            ("It is OK", "medium"),
            ("Yes, I like it", "low"),
        ],
        "next_state": Onboarding.heat_sensitivity,
    },
    {
        "state": Onboarding.heat_sensitivity,
        "field": "heat_sensitivity",
        "question": "Do you like hot weather?",
        "buttons": [
            ("No, I do not like it", "high"),
            ("It is OK", "medium"),
            ("Yes, I like it", "low"),
        ],
        "next_state": Onboarding.bad_weather_sensitivity,
    },
    {
        "state": Onboarding.bad_weather_sensitivity,
        "field": "bad_weather_sensitivity",
        "question": "Do you like rain, snow, and wind?",
        "buttons": [
            ("No, I do not like it", "high"),
            ("It is OK", "medium"),
            ("Yes, I like it", "low"),
        ],
        "next_state": Onboarding.recommendation_style,
    },
    {
        "state": Onboarding.recommendation_style,
        "field": "recommendation_style",
        "question": "What kind of advice do you want?",
        "buttons": [
            ("Only tips", "practical"),
            ("Tips and ideas", "activities"),
            ("Tips and fun", "cozy_fun"),
        ],
        "next_state": Onboarding.tone,
    },
    {
        "state": Onboarding.tone,
        "field": "tone",
        "question": "How should I talk to you?",
        "buttons": [
            ("Formal", "formal"),
            ("Simple", "casual"),
            ("Funny", "humorous"),
        ],
        "next_state": Onboarding.daytime_alerts,
    },
    {
        "state": Onboarding.daytime_alerts,
        "field": "daytime_alerts",
        "question": "When should I tell you about weather changes?",
        "buttons": [
            ("All updates", "all"),
            ("Important only", "important"),
            ("Only morning and evening", "none"),
        ],
        "next_state": None,
    },
]

STEP_BY_STATE = {config["state"].state: config for config in STEP_CONFIGS}

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


def build_keyboard(buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=callback_data)]
            for label, callback_data in buttons
        ]
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return build_keyboard(
        [
            ("Today advice", "menu:today"),
            ("Tomorrow advice", "menu:tomorrow"),
            ("Preferences", "menu:preferences"),
            ("Quick Requests", "menu:quick_requests"),
        ]
    )


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Create .env from .env.example.")
    return database_url


def setup_database() -> None:
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(CREATE_USERS_TABLE_SQL)
            cursor.execute(CREATE_PREFERENCES_TABLE_SQL)
            cursor.execute(CREATE_WEATHER_FORECASTS_TABLE_SQL)
            cursor.execute(CREATE_WEATHER_FORECASTS_INDEX_SQL)


def row_to_user(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "telegram_id": row[1],
        "username": row[2],
        "created_at": row[3],
        "updated_at": row[4],
    }


def row_to_preferences(row: tuple[Any, ...] | None) -> dict[str, Any] | None:
    if row is None:
        return None

    return {
        "id": row[0],
        "user_id": row[1],
        "postal_code_id": row[2],
        "postal_code": row[3],
        "city": row[4],
        "canton": row[5],
        "latitude": row[6],
        "longitude": row[7],
        "morning_time": row[8],
        "evening_time": row[9],
        "quiet_hours_enabled": row[10],
        "quiet_hours_start": row[11],
        "quiet_hours_end": row[12],
        "cold_sensitivity": row[13],
        "heat_sensitivity": row[14],
        "bad_weather_sensitivity": row[15],
        "recommendation_style": row[16],
        "tone": row[17],
        "daytime_alerts": row[18],
        "completed": row[19],
        "created_at": row[20],
        "updated_at": row[21],
    }


def upsert_user(telegram_id: int, username: str | None) -> dict[str, Any]:
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(UPSERT_USER_SQL, (telegram_id, username))
            row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Could not create or update Telegram user.")

    return row_to_user(row)


def get_saved_preferences(user_id: int) -> dict[str, Any] | None:
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(SAVED_PREFERENCES_SQL, (user_id,))
            row = cursor.fetchone()

    return row_to_preferences(row)


def delete_preferences(user_id: int) -> None:
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM preferences WHERE user_id = %s;", (user_id,))


def lookup_postal_code(postal_code: str) -> list[Location]:
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(POSTAL_CODE_QUERY, (postal_code,))
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "postal_code": row[1],
            "city": row[2],
            "canton": row[3],
            "latitude": row[4],
            "longitude": row[5],
        }
        for row in rows
    ]


def save_preferences(telegram_id: int, username: str | None, data: dict[str, Any]) -> int:
    user = upsert_user(telegram_id, username)

    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM preferences WHERE user_id = %s;", (user["id"],))
            cursor.execute(
                INSERT_PREFERENCES_SQL,
                (
                    user["id"],
                    data.get("postal_code_id"),
                    data.get("morning_time"),
                    data.get("evening_time"),
                    data.get("quiet_hours_enabled"),
                    data.get("quiet_hours_start"),
                    data.get("quiet_hours_end"),
                    data.get("cold_sensitivity"),
                    data.get("heat_sensitivity"),
                    data.get("bad_weather_sensitivity"),
                    data.get("recommendation_style"),
                    data.get("tone"),
                    data.get("daytime_alerts"),
                ),
            )
            row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Could not save preferences.")

    return row[0]


def get_open_meteo_forecast(latitude: float, longitude: float, forecast_days: int = 7) -> dict[str, Any]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": "Europe/Zurich",
        "forecast_days": forecast_days,
        "current": (
            "temperature_2m,apparent_temperature,precipitation,weather_code,"
            "cloud_cover,wind_speed_10m,wind_gusts_10m"
        ),
        "hourly": (
            "temperature_2m,apparent_temperature,precipitation_probability,"
            "precipitation,rain,showers,snowfall,weather_code,cloud_cover,"
            "wind_speed_10m,wind_gusts_10m,uv_index,is_day"
        ),
        "daily": (
            "weather_code,temperature_2m_max,temperature_2m_min,"
            "apparent_temperature_max,apparent_temperature_min,sunrise,sunset,"
            "daylight_duration,sunshine_duration,uv_index_max,precipitation_sum,"
            "rain_sum,showers_sum,snowfall_sum,precipitation_probability_max,"
            "wind_speed_10m_max,wind_gusts_10m_max"
        ),
    }
    logger.info("open-meteo request latitude=%s longitude=%s days=%s", latitude, longitude, forecast_days)

    response = httpx.get(OPEN_METEO_URL, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def save_weather_forecast(postal_code_id: int, weather_json: dict[str, Any]) -> int:
    forecast_date = datetime.now(ZURICH_TZ).date()

    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                INSERT_WEATHER_FORECAST_SQL,
                (postal_code_id, forecast_date, Jsonb(weather_json)),
            )
            row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Could not save weather forecast.")

    logger.info(
        "weather forecast saved postal_code_id=%s forecast_date=%s forecast_id=%s",
        postal_code_id,
        forecast_date,
        row[0],
    )
    return row[0]


def get_location_preferences_for_telegram_id(telegram_id: int) -> dict[str, Any] | None:
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(USER_LOCATION_PREFERENCES_SQL, (telegram_id,))
            row = cursor.fetchone()

    return row_to_preferences(row)


def get_latest_weather_status(user_id: int) -> dict[str, Any] | None:
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(LATEST_WEATHER_STATUS_SQL, (user_id,))
            row = cursor.fetchone()

    if row is None:
        return None

    return {
        "forecast_exists": row[0] is not None,
        "forecast_id": row[0],
        "forecast_date": row[1],
        "forecast_type": row[2],
        "fetched_at": row[3],
        "postal_code": row[4],
        "city": row[5],
    }


def weather_status_text(status: dict[str, Any] | None) -> str:
    if status is None:
        return "No saved location"

    location = f"{status.get('postal_code')} {status.get('city')}"
    if not status.get("forecast_exists"):
        return f"No forecast saved for {location}"

    return (
        f"Yes, forecast_id={status.get('forecast_id')} for {location}, "
        f"fetched_at={status.get('fetched_at')}"
    )


def get_latest_weather_for_user(telegram_id: int) -> dict[str, Any]:
    preferences = get_location_preferences_for_telegram_id(telegram_id)
    if preferences is None:
        raise RuntimeError("No completed preferences found for this user.")

    latitude = preferences.get("latitude")
    longitude = preferences.get("longitude")
    postal_code_id = preferences.get("postal_code_id")

    if latitude is None or longitude is None or postal_code_id is None:
        raise RuntimeError("Saved location does not have coordinates.")

    weather_json = get_open_meteo_forecast(float(latitude), float(longitude))
    forecast_id = save_weather_forecast(int(postal_code_id), weather_json)
    location = {
        "postal_code_id": postal_code_id,
        "postal_code": preferences.get("postal_code"),
        "city": preferences.get("city"),
        "canton": preferences.get("canton"),
        "latitude": latitude,
        "longitude": longitude,
    }

    return {
        "weather_json": weather_json,
        "preferences": preferences,
        "location": location,
        "forecast_id": forecast_id,
    }


def selected_location_text(data: dict[str, Any]) -> str:
    postal_code = data.get("postal_code") or data.get("pending_postal_code")
    city = data.get("city") or data.get("pending_city")

    if not postal_code or not city:
        return "Not selected"

    return f"{postal_code} → {city}"


def normalized_step_update(field: str, value: str) -> dict[str, Any]:
    if field == "quiet_hours":
        return QUIET_HOURS_VALUES[value]
    return {field: value}


def number_or_none(value: Any) -> float | None:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def max_number(values: list[Any], default: float = 0) -> float:
    numbers = [number for number in (number_or_none(value) for value in values) if number is not None]
    return max(numbers, default=default)


def average_number(values: list[Any], default: float = 0) -> float:
    numbers = [number for number in (number_or_none(value) for value in values) if number is not None]
    if not numbers:
        return default
    return sum(numbers) / len(numbers)


def forecast_date_for(day: str) -> date:
    today = datetime.now(ZURICH_TZ).date()
    if day == "tomorrow":
        return today + timedelta(days=1)
    return today


def hourly_rows_for_date(weather_json: dict[str, Any], day: str) -> list[dict[str, Any]]:
    target_date = forecast_date_for(day)
    hourly = weather_json.get("hourly") or {}
    times = hourly.get("time") or []
    rows = []

    for index, time_text in enumerate(times):
        try:
            hour_time = datetime.fromisoformat(time_text)
        except (TypeError, ValueError):
            continue

        if hour_time.date() != target_date:
            continue

        row = {"time": hour_time}
        for key, values in hourly.items():
            if key == "time" or not isinstance(values, list) or index >= len(values):
                continue
            row[key] = values[index]
        rows.append(row)

    return rows


def best_outdoor_time(rows: list[dict[str, Any]]) -> str:
    periods = {
        "morning": (6, 12),
        "afternoon": (12, 18),
        "evening": (18, 22),
    }
    scores = []

    for name, (start_hour, end_hour) in periods.items():
        period_rows = [
            row
            for row in rows
            if start_hour <= row["time"].hour < end_hour
        ]
        if not period_rows:
            continue

        precipitation_score = average_number(
            [row.get("precipitation_probability") for row in period_rows],
            default=100,
        )
        temperature = average_number(
            [row.get("apparent_temperature") for row in period_rows],
            default=18,
        )
        wind_score = average_number([row.get("wind_gusts_10m") for row in period_rows])
        snow_score = max_number([row.get("snowfall") for row in period_rows]) * 40
        comfort_penalty = abs(temperature - 18) * 2
        scores.append((precipitation_score + comfort_penalty + wind_score * 0.5 + snow_score, name))

    if not scores:
        return "not recommended"

    score, name = min(scores)
    if score >= 85:
        return "not recommended"
    return name


def analyze_weather(
    weather_json: dict[str, Any],
    preferences: dict[str, Any],
    location: dict[str, Any],
    day: str = "today",
) -> dict[str, Any]:
    rows = hourly_rows_for_date(weather_json, day)
    current = weather_json.get("current") or {}

    apparent_values = [row.get("apparent_temperature") for row in rows]
    if not apparent_values and day == "today":
        apparent_values = [current.get("apparent_temperature")]

    cold_thresholds = {"high": 14, "medium": 10, "low": 6}
    heat_thresholds = {"high": 24, "medium": 28, "low": 32}
    rain_thresholds = {"high": 30, "medium": 50, "low": 70}

    cold_threshold = cold_thresholds.get(preferences.get("cold_sensitivity"), 10)
    heat_threshold = heat_thresholds.get(preferences.get("heat_sensitivity"), 28)
    rain_threshold = rain_thresholds.get(preferences.get("bad_weather_sensitivity"), 50)

    min_apparent = min(
        [value for value in (number_or_none(value) for value in apparent_values) if value is not None],
        default=None,
    )
    max_apparent = max(
        [value for value in (number_or_none(value) for value in apparent_values) if value is not None],
        default=None,
    )
    max_precipitation_probability = max_number(
        [row.get("precipitation_probability") for row in rows],
    )
    max_snowfall = max_number([row.get("snowfall") for row in rows])
    max_wind_gusts = max_number(
        [row.get("wind_gusts_10m") for row in rows],
        default=number_or_none(current.get("wind_gusts_10m")) or 0,
    )

    feels_cold = min_apparent is not None and min_apparent <= cold_threshold
    feels_hot = max_apparent is not None and max_apparent >= heat_threshold
    rain_expected = max_precipitation_probability >= rain_threshold
    snow_expected = max_snowfall > 0
    windy = max_wind_gusts >= 40
    outdoor_time = best_outdoor_time(rows)

    items_to_take = []
    clothing = []

    if rain_expected:
        items_to_take.append("umbrella")
    if snow_expected:
        items_to_take.append("waterproof shoes")
    if feels_cold:
        clothing.append("warm jacket")
    if feels_hot:
        clothing.append("light clothes")
    if rain_expected:
        clothing.append("rain jacket")
    if windy:
        clothing.append("windproof jacket")

    if outdoor_time == "not recommended":
        activity_hint = "Outdoor plans do not look great today."
    elif rain_expected:
        activity_hint = f"Better to do outdoor plans in the {outdoor_time}."
    else:
        activity_hint = f"The {outdoor_time} looks best for going outside."

    summary_parts = []
    if feels_cold:
        summary_parts.append("cool")
    if feels_hot:
        summary_parts.append("warm")
    if rain_expected:
        summary_parts.append("rainy")
    if snow_expected:
        summary_parts.append("snowy")
    if windy:
        summary_parts.append("windy")

    if summary_parts:
        summary = f"{', '.join(summary_parts).capitalize()} day."
    else:
        summary = "Fair day without major weather issues."

    analysis = {
        "location": location.get("city"),
        "day": day,
        "feels_cold": feels_cold,
        "feels_hot": feels_hot,
        "rain_expected": rain_expected,
        "snow_expected": snow_expected,
        "windy": windy,
        "best_outdoor_time": outdoor_time,
        "items_to_take": items_to_take,
        "clothing": clothing,
        "activity_hint": activity_hint,
        "summary": summary,
    }
    logger.info("weather analysis location=%s day=%s facts=%s", location.get("city"), day, analysis)
    return analysis


def readable_items(items: list[str]) -> str:
    labels = {
        "umbrella": "an umbrella",
        "waterproof shoes": "waterproof shoes",
        "warm jacket": "a warm jacket",
        "light clothes": "light clothes",
        "rain jacket": "a rain jacket",
        "windproof jacket": "a windproof jacket",
    }
    readable = [labels.get(item, item) for item in items]

    if not readable:
        return ""
    if len(readable) == 1:
        return readable[0]
    return f"{', '.join(readable[:-1])} and {readable[-1]}"


def build_today_advice_message(analysis: dict[str, Any]) -> str:
    location = analysis.get("location") or "your location"
    take_items = analysis.get("clothing", []) + analysis.get("items_to_take", [])
    advice = readable_items(take_items)

    if advice:
        first_sentence = f"Today in {location}: Take {advice}."
    else:
        first_sentence = f"Today in {location}: No special extras needed."

    outdoor_time = analysis.get("best_outdoor_time")
    if outdoor_time == "not recommended":
        second_sentence = "Outdoor plans do not look great today."
    else:
        second_sentence = f"{str(outdoor_time).capitalize()} looks better for going outside."

    return f"{first_sentence} {second_sentence}"


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


async def ask_postal_code(message: Message, state: FSMContext) -> None:
    await state.set_state(Onboarding.postal_code)
    logger.info("onboarding transition user_id=%s step=postal_code", message.from_user.id)
    await message.answer("Please enter your Swiss postal code.\nExample: 8001")


async def ask_postal_city_choice(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    postal_code = data.get("pending_postal_code")
    locations = data.get("pending_locations") or []

    if not postal_code or not locations:
        await ask_postal_code(message, state)
        return

    await state.set_state(Onboarding.postal_city)
    logger.info(
        "onboarding transition user_id=%s step=postal_city postal_code=%s options=%s",
        message.from_user.id,
        postal_code,
        len(locations),
    )
    await message.answer(
        f"I found several places for {postal_code}. Please choose your city.",
        reply_markup=build_keyboard(
            [
                (str(location["city"]), f"postal_city:{index}")
                for index, location in enumerate(locations)
            ]
        ),
    )


async def ask_postal_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    postal_code = data.get("pending_postal_code")
    city = data.get("pending_city")

    if not postal_code or not city:
        await ask_postal_code(message, state)
        return

    await state.set_state(Onboarding.postal_confirm)
    logger.info(
        "onboarding transition user_id=%s step=postal_confirm postal_code=%s city=%s",
        message.from_user.id,
        postal_code,
        city,
    )
    await message.answer(
        f"{postal_code} → {city}\nIs this correct?",
        reply_markup=build_keyboard(
            [
                ("Yes", "postal:yes"),
                ("Change", "postal:change"),
            ]
        ),
    )


async def ask_configured_step(message: Message, step_state: State) -> None:
    config = STEP_BY_STATE[step_state.state]
    await state_log_message(message, config["field"])
    await message.answer(
        config["question"],
        reply_markup=build_keyboard(
            [
                (label, f"set:{config['field']}:{value}")
                for label, value in config["buttons"]
            ]
        ),
    )


async def state_log_message(message: Message, step: str) -> None:
    logger.info("onboarding transition user_id=%s step=%s", message.from_user.id, step)


async def repeat_current_question(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()

    if current_state == Onboarding.postal_code.state:
        await ask_postal_code(message, state)
        return

    if current_state == Onboarding.postal_city.state:
        await ask_postal_city_choice(message, state)
        return

    if current_state == Onboarding.postal_confirm.state:
        await ask_postal_confirmation(message, state)
        return

    config = STEP_BY_STATE.get(current_state)
    if config:
        await ask_configured_step(message, config["state"])
        return

    await start_onboarding(message, state)


async def start_onboarding(
    message: Message,
    state: FSMContext,
    include_welcome: bool = True,
) -> None:
    await state.clear()

    if include_welcome:
        await message.answer(WELCOME_TEXT)

    logger.info("onboarding started user_id=%s", message.from_user.id)
    await ask_postal_code(message, state)


async def complete_onboarding(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    telegram_id, username = telegram_user_data(callback)

    try:
        preference_id = await asyncio.to_thread(save_preferences, telegram_id, username, data)
    except (psycopg.Error, RuntimeError):
        logger.exception("preferences save failed telegram_id=%s", telegram_id)
        await callback.message.answer("I could not save your preferences. Please try again later.")
        return

    await state.clear()
    logger.info(
        "preferences saved to PostgreSQL telegram_id=%s preference_id=%s postal_code_id=%s",
        telegram_id,
        preference_id,
        data.get("postal_code_id"),
    )
    await callback.message.answer("Preferences saved.", reply_markup=main_menu_keyboard())


@dp.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    user = await ensure_user(message)
    if user is None:
        return

    logger.info("/start user_id=%s db_user_id=%s", message.from_user.id, user["id"])

    try:
        saved_preferences = await asyncio.to_thread(get_saved_preferences, user["id"])
    except psycopg.Error:
        logger.exception("preferences lookup failed user_id=%s", user["id"])
        await message.answer("I could not load your preferences. Please try again later.")
        return

    if saved_preferences:
        await state.clear()
        await message.answer("Your preferences are ready.", reply_markup=main_menu_keyboard())
        return

    await start_onboarding(message, state)


@dp.message(Command("reset"))
async def handle_reset(message: Message, state: FSMContext) -> None:
    user = await ensure_user(message)
    if user is None:
        return

    await state.clear()

    try:
        await asyncio.to_thread(delete_preferences, user["id"])
    except psycopg.Error:
        logger.exception("preferences delete failed user_id=%s", user["id"])
        await message.answer("I could not reset your preferences. Please try again later.")
        return

    logger.info("/reset user_id=%s db_user_id=%s", message.from_user.id, user["id"])
    await message.answer("Preferences reset. Let's set them up again.")
    await start_onboarding(message, state, include_welcome=False)


@dp.message(Command("debug"))
async def handle_debug(message: Message, state: FSMContext) -> None:
    user = await ensure_user(message)
    if user is None:
        return

    current_state = await state.get_state()
    draft_data = await state.get_data()

    try:
        saved_preferences = await asyncio.to_thread(get_saved_preferences, user["id"])
        weather_status = await asyncio.to_thread(get_latest_weather_status, user["id"])
    except psycopg.Error:
        logger.exception("debug preferences lookup failed user_id=%s", user["id"])
        await message.answer("I could not load debug data. Please try again later.")
        return

    await message.answer(
        "\n".join(
            [
                "Debug state:",
                f"Current user: {pformat(user)}",
                f"Current onboarding state: {current_state or 'none'}",
                f"Selected location: {selected_location_text(draft_data)}",
                f"Draft data: {pformat(draft_data)}",
                f"Saved preferences: {pformat(saved_preferences or {})}",
                f"Latest weather forecast: {weather_status_text(weather_status)}",
            ]
        )
    )


@dp.message(Onboarding.postal_code)
async def handle_postal_code(message: Message, state: FSMContext) -> None:
    postal_code = (message.text or "").strip()
    user_id = message.from_user.id

    if not (postal_code.isdigit() and len(postal_code) == 4):
        logger.info("invalid postal_code user_id=%s value=%r", user_id, postal_code)
        await message.answer("Please enter exactly 4 digits.\nExample: 8001")
        return

    try:
        locations = await asyncio.to_thread(lookup_postal_code, postal_code)
    except psycopg.Error:
        logger.exception("postal code lookup failed user_id=%s postal_code=%s", user_id, postal_code)
        await message.answer("I could not look up postal codes right now. Please try again later.")
        return

    logger.info(
        "postal code lookup user_id=%s postal_code=%s result_count=%s",
        user_id,
        postal_code,
        len(locations),
    )

    if not locations:
        await state.update_data(
            pending_postal_code=None,
            pending_locations=[],
            pending_postal_code_id=None,
            pending_city=None,
        )
        await message.answer("I could not find this Swiss postal code. Please try again.")
        await ask_postal_code(message, state)
        return

    await state.update_data(
        pending_postal_code=postal_code,
        pending_locations=locations,
        pending_postal_code_id=None,
        pending_city=None,
    )

    if len(locations) > 1:
        await ask_postal_city_choice(message, state)
        return

    location = locations[0]
    await state.update_data(
        pending_postal_code_id=location["id"],
        pending_city=location["city"],
    )
    await ask_postal_confirmation(message, state)


@dp.callback_query(F.data.startswith("postal_city:"))
async def handle_postal_city_choice(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    current_state = await state.get_state()

    if current_state != Onboarding.postal_city.state:
        await repeat_current_question(callback.message, state)
        return

    data = await state.get_data()
    locations = data.get("pending_locations") or []
    index_text = (callback.data or "").split(":", maxsplit=1)[1]

    try:
        location = locations[int(index_text)]
    except (ValueError, IndexError, TypeError):
        await repeat_current_question(callback.message, state)
        return

    await state.update_data(
        pending_postal_code=location["postal_code"],
        pending_postal_code_id=location["id"],
        pending_city=location["city"],
    )
    logger.info(
        "onboarding selected postal city user_id=%s postal_code_id=%s city=%s",
        callback.from_user.id,
        location["id"],
        location["city"],
    )
    await ask_postal_confirmation(callback.message, state)


@dp.callback_query(F.data.startswith("postal:"))
async def handle_postal_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    current_state = await state.get_state()

    if current_state != Onboarding.postal_confirm.state:
        await repeat_current_question(callback.message, state)
        return

    action = (callback.data or "").split(":", maxsplit=1)[1]
    user_id = callback.from_user.id

    if action == "change":
        logger.info("onboarding postal change user_id=%s", user_id)
        await state.update_data(
            pending_postal_code=None,
            pending_locations=[],
            pending_postal_code_id=None,
            pending_city=None,
        )
        await ask_postal_code(callback.message, state)
        return

    if action != "yes":
        await repeat_current_question(callback.message, state)
        return

    data = await state.get_data()
    if not data.get("pending_postal_code_id"):
        await ask_postal_code(callback.message, state)
        return

    await state.update_data(postal_code_id=data.get("pending_postal_code_id"))

    logger.info(
        "onboarding confirmed postal code user_id=%s postal_code_id=%s",
        user_id,
        data.get("pending_postal_code_id"),
    )
    await state.set_state(Onboarding.morning_time)
    await ask_configured_step(callback.message, Onboarding.morning_time)


@dp.callback_query(F.data.startswith("set:"))
async def handle_onboarding_choice(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    current_state = await state.get_state()
    config = STEP_BY_STATE.get(current_state)

    if not config:
        await repeat_current_question(callback.message, state)
        return

    _, field, value = (callback.data or "").split(":", maxsplit=2)
    valid_values = {button_value for _, button_value in config["buttons"]}
    if field != config["field"] or value not in valid_values:
        await repeat_current_question(callback.message, state)
        return

    updates = normalized_step_update(field, value)
    await state.update_data(**updates)

    logger.info(
        "onboarding answer user_id=%s step=%s value=%s",
        callback.from_user.id,
        field,
        value,
    )

    next_state = config["next_state"]
    if next_state is None:
        await complete_onboarding(callback, state)
        return

    await state.set_state(next_state)
    await ask_configured_step(callback.message, next_state)


@dp.callback_query(F.data == "menu:today")
async def handle_today_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    telegram_id = callback.from_user.id

    try:
        result = await asyncio.to_thread(get_latest_weather_for_user, telegram_id)
    except httpx.HTTPError:
        logger.exception("open-meteo forecast failed telegram_id=%s", telegram_id)
        await callback.message.answer("I could not fetch the weather right now. Please try again later.")
        return
    except (psycopg.Error, RuntimeError):
        logger.exception("today advice failed telegram_id=%s", telegram_id)
        await callback.message.answer("I could not load your weather preferences. Use /start or /reset.")
        return

    analysis = analyze_weather(
        result["weather_json"],
        result["preferences"],
        result["location"],
        day="today",
    )
    await callback.message.answer(build_today_advice_message(analysis))


@dp.callback_query(F.data == "menu:tomorrow")
async def handle_tomorrow_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("Tomorrow advice will be added soon.")


@dp.callback_query(F.data == "menu:preferences")
async def handle_preferences_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("To change preferences, use /reset and answer the questions again.")


@dp.callback_query(F.data == "menu:quick_requests")
async def handle_quick_requests_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("Quick requests will be added soon.")


@dp.message()
async def handle_unexpected_message(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    user_id = message.from_user.id

    if current_state:
        logger.info(
            "unexpected text user_id=%s state=%s text=%r",
            user_id,
            current_state,
            message.text,
        )
        await message.answer("Please answer the current question.")
        await repeat_current_question(message, state)
        return

    user = await ensure_user(message)
    if user is None:
        return

    try:
        saved_preferences = await asyncio.to_thread(get_saved_preferences, user["id"])
    except psycopg.Error:
        logger.exception("preferences lookup failed user_id=%s", user["id"])
        await message.answer("I could not load your preferences. Please try again later.")
        return

    if saved_preferences:
        await message.answer("Use the menu below, /debug, or /reset.", reply_markup=main_menu_keyboard())
        return

    await start_onboarding(message, state)


async def main() -> None:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not set. Create .env from .env.example.")

    await asyncio.to_thread(setup_database)

    bot = Bot(token=bot_token)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
