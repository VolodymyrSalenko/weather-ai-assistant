from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from config import DATABASE_URL, ZURICH_TZ


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

CREATE_NOTIFICATION_LOG_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS notification_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    notification_type TEXT CHECK (notification_type IN ('morning', 'evening', 'weather_change_today')),
    notification_date DATE NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, notification_type, notification_date)
);
"""

DROP_NOTIFICATION_LOG_TYPE_CHECK_SQL = """
ALTER TABLE notification_log
DROP CONSTRAINT IF EXISTS notification_log_notification_type_check;
"""

ADD_NOTIFICATION_LOG_TYPE_CHECK_SQL = """
ALTER TABLE notification_log
ADD CONSTRAINT notification_log_notification_type_check
CHECK (notification_type IN ('morning', 'evening', 'weather_change_today'));
"""

POSTAL_CODE_QUERY = """
SELECT id, postal_code, city, canton, latitude, longitude
FROM postal_codes
WHERE postal_code = %s
ORDER BY city;
"""

FIND_POSTAL_CODE_LOCATION_SQL = """
SELECT id, postal_code, city, canton, latitude, longitude
FROM postal_codes
WHERE
    (%s = TRUE AND postal_code = %s)
    OR (%s = FALSE AND city ILIKE %s)
ORDER BY
    CASE
        WHEN lower(city) = lower(%s) THEN 0
        WHEN city ILIKE %s THEN 1
        ELSE 2
    END,
    city,
    postal_code
LIMIT 1;
"""

ACTIVE_POSTAL_CODE_LOCATIONS_SQL = """
SELECT DISTINCT pc.id, pc.postal_code, pc.city, pc.canton, pc.latitude, pc.longitude
FROM preferences p
JOIN postal_codes pc ON pc.id = p.postal_code_id
WHERE p.completed = TRUE
ORDER BY pc.postal_code, pc.city;
"""

ALL_POSTAL_CODE_LOCATIONS_SQL = """
SELECT id, postal_code, city, canton, latitude, longitude
FROM postal_codes
ORDER BY postal_code, city;
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

LATEST_STORED_WEATHER_FORECAST_SQL = """
SELECT raw_json
FROM weather_forecasts
WHERE postal_code_id = %s
    AND source = 'open_meteo'
    AND forecast_type = 'full'
    AND forecast_date = %s
ORDER BY fetched_at DESC
LIMIT 1;
"""

COMPLETED_PREFERENCES_FOR_NOTIFICATIONS_SQL = """
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
    p.updated_at,
    u.telegram_id
FROM users u
JOIN preferences p ON p.user_id = u.id
JOIN postal_codes pc ON pc.id = p.postal_code_id
WHERE p.completed = TRUE
ORDER BY p.updated_at DESC;
"""

COMPLETED_PREFERENCES_FOR_POSTAL_CODE_SQL = """
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
    p.updated_at,
    u.telegram_id
FROM users u
JOIN preferences p ON p.user_id = u.id
JOIN postal_codes pc ON pc.id = p.postal_code_id
WHERE p.completed = TRUE AND p.postal_code_id = %s
ORDER BY p.updated_at DESC;
"""

CLEANUP_OLD_WEATHER_FORECASTS_SQL = """
DELETE FROM weather_forecasts
WHERE fetched_at < CURRENT_TIMESTAMP - (%s::int * INTERVAL '1 day');
"""

MARK_NOTIFICATION_SENT_SQL = """
INSERT INTO notification_log (user_id, notification_type, notification_date)
VALUES (%s, %s, %s)
ON CONFLICT (user_id, notification_type, notification_date) DO NOTHING
RETURNING id;
"""

HAS_NOTIFICATION_BEEN_SENT_SQL = """
SELECT 1
FROM notification_log
WHERE user_id = %s
    AND notification_type = %s
    AND notification_date = %s
LIMIT 1;
"""


def setup_database() -> None:
    """Create app tables if they do not exist."""
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(CREATE_USERS_TABLE_SQL)
            cursor.execute(CREATE_PREFERENCES_TABLE_SQL)
            cursor.execute(CREATE_WEATHER_FORECASTS_TABLE_SQL)
            cursor.execute(CREATE_WEATHER_FORECASTS_INDEX_SQL)
            cursor.execute(CREATE_NOTIFICATION_LOG_TABLE_SQL)
            cursor.execute(DROP_NOTIFICATION_LOG_TYPE_CHECK_SQL)
            cursor.execute(ADD_NOTIFICATION_LOG_TYPE_CHECK_SQL)


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


def row_to_postal_code_location(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "postal_code": row[1],
        "city": row[2],
        "canton": row[3],
        "latitude": row[4],
        "longitude": row[5],
    }


def row_to_notification_preferences(row: tuple[Any, ...]) -> dict[str, Any]:
    preferences = row_to_preferences(row[:22])
    if preferences is None:
        raise RuntimeError("Could not read notification preferences.")

    preferences["telegram_id"] = row[22]
    return preferences


def upsert_user(telegram_id: int, username: str | None) -> dict[str, Any]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(UPSERT_USER_SQL, (telegram_id, username))
            row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Could not create or update user.")

    return row_to_user(row)


def get_saved_preferences(user_id: int) -> dict[str, Any] | None:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(SAVED_PREFERENCES_SQL, (user_id,))
            row = cursor.fetchone()

    return row_to_preferences(row)


def delete_preferences(user_id: int) -> None:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM preferences WHERE user_id = %s;", (user_id,))


def lookup_postal_code(postal_code: str) -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(POSTAL_CODE_QUERY, (postal_code,))
            rows = cursor.fetchall()

    return [row_to_postal_code_location(row) for row in rows]


def find_postal_code_location(query: str) -> dict[str, Any] | None:
    cleaned_query = query.strip()
    is_postal_code = cleaned_query.isdigit() and len(cleaned_query) == 4
    city_query = f"%{cleaned_query}%"
    city_prefix_query = f"{cleaned_query}%"

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                FIND_POSTAL_CODE_LOCATION_SQL,
                (
                    is_postal_code,
                    cleaned_query,
                    is_postal_code,
                    city_query,
                    cleaned_query,
                    city_prefix_query,
                ),
            )
            row = cursor.fetchone()

    if row is None:
        return None

    return row_to_postal_code_location(row)


def get_active_postal_code_locations() -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(ACTIVE_POSTAL_CODE_LOCATIONS_SQL)
            rows = cursor.fetchall()

    return [row_to_postal_code_location(row) for row in rows]


def get_all_postal_code_locations() -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(ALL_POSTAL_CODE_LOCATIONS_SQL)
            rows = cursor.fetchall()

    return [row_to_postal_code_location(row) for row in rows]


def save_preferences(telegram_id: int, username: str | None, data: dict[str, Any]) -> int:
    user = upsert_user(telegram_id, username)

    with psycopg.connect(DATABASE_URL) as conn:
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


def get_location_preferences_for_telegram_id(telegram_id: int) -> dict[str, Any] | None:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(USER_LOCATION_PREFERENCES_SQL, (telegram_id,))
            row = cursor.fetchone()

    return row_to_preferences(row)


def get_completed_preferences_for_notifications() -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(COMPLETED_PREFERENCES_FOR_NOTIFICATIONS_SQL)
            rows = cursor.fetchall()

    return [row_to_notification_preferences(row) for row in rows]


def get_completed_preferences_for_postal_code(postal_code_id: int) -> list[dict[str, Any]]:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(COMPLETED_PREFERENCES_FOR_POSTAL_CODE_SQL, (postal_code_id,))
            rows = cursor.fetchall()

    return [row_to_notification_preferences(row) for row in rows]


def has_notification_been_sent(
    user_id: int,
    notification_type: str,
    notification_date: date,
) -> bool:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                HAS_NOTIFICATION_BEEN_SENT_SQL,
                (user_id, notification_type, notification_date),
            )
            row = cursor.fetchone()

    return row is not None


def log_notification_sent(user_id: int, notification_type: str, notification_date: date) -> bool:
    return mark_notification_sent(user_id, notification_type, notification_date)


def mark_notification_sent(user_id: int, notification_type: str, notification_date: date) -> bool:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                MARK_NOTIFICATION_SENT_SQL,
                (user_id, notification_type, notification_date),
            )
            row = cursor.fetchone()

    return row is not None


def get_latest_stored_weather_forecast(postal_code_id: int) -> dict[str, Any] | None:
    forecast_date = datetime.now(ZURICH_TZ).date()

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(LATEST_STORED_WEATHER_FORECAST_SQL, (postal_code_id, forecast_date))
            row = cursor.fetchone()

    if row is None:
        return None

    return row[0]


def cleanup_old_weather_forecasts(days: int = 14) -> None:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(CLEANUP_OLD_WEATHER_FORECASTS_SQL, (days,))


def save_weather_forecast(postal_code_id: int, weather_json: dict[str, Any]) -> int:
    forecast_date = datetime.now(ZURICH_TZ).date()

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                INSERT_WEATHER_FORECAST_SQL,
                (postal_code_id, forecast_date, Jsonb(weather_json)),
            )
            row = cursor.fetchone()

    if row is None:
        raise RuntimeError("Could not save weather forecast.")

    return row[0]
