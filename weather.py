"""Fetch Open-Meteo forecasts, store them, and convert raw weather data into structured context."""

from datetime import date, datetime, timedelta
from typing import Any

import httpx

from config import OPEN_METEO_URL, ZURICH_TZ
from database import (
    get_latest_stored_weather_forecast,
    get_location_preferences_for_telegram_id,
    save_weather_forecast,
)


def get_open_meteo_forecast(latitude: float, longitude: float, forecast_days: int = 7) -> dict[str, Any]:
    """Fetch raw weather data from Open-Meteo."""
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

    response = httpx.get(OPEN_METEO_URL, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_and_store_weather_for_location(location: dict[str, Any]) -> int:
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    postal_code_id = location.get("id") or location.get("postal_code_id")

    if latitude is None or longitude is None or postal_code_id is None:
        raise RuntimeError("Location does not have coordinates.")

    weather_json = get_open_meteo_forecast(float(latitude), float(longitude), forecast_days=7)
    return save_weather_forecast(int(postal_code_id), weather_json)


def get_weather_for_user_from_db_or_fetch(telegram_id: int) -> dict[str, Any]:
    preferences = get_location_preferences_for_telegram_id(telegram_id)

    if preferences is None:
        raise RuntimeError("No completed preferences found.")

    latitude = preferences.get("latitude")
    longitude = preferences.get("longitude")
    postal_code_id = preferences.get("postal_code_id")

    if latitude is None or longitude is None or postal_code_id is None:
        raise RuntimeError("Saved location does not have coordinates.")

    location = {
        "postal_code_id": postal_code_id,
        "postal_code": preferences.get("postal_code"),
        "city": preferences.get("city"),
        "canton": preferences.get("canton"),
        "latitude": latitude,
        "longitude": longitude,
    }

    weather_json = get_latest_stored_weather_forecast(int(postal_code_id))
    forecast_id = None

    if weather_json is None:
        forecast_id = fetch_and_store_weather_for_location(location)
        weather_json = get_latest_stored_weather_forecast(int(postal_code_id))

    if weather_json is None:
        raise RuntimeError("Could not load weather forecast.")

    return {
        "weather_json": weather_json,
        "preferences": preferences,
        "location": location,
        "forecast_id": forecast_id,
    }


def get_latest_weather_for_user(telegram_id: int) -> dict[str, Any]:
    """Load user location, fetch weather, save raw JSON, return data for analysis."""
    preferences = get_location_preferences_for_telegram_id(telegram_id)

    if preferences is None:
        raise RuntimeError("No completed preferences found.")

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


def number_or_none(value: Any) -> float | None:
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

    if day.startswith("date:"):
        return date.fromisoformat(day.split(":", maxsplit=1)[1])

    if day == "tomorrow":
        return today + timedelta(days=1)

    if day == "day_after_tomorrow":
        return today + timedelta(days=2)

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
    """Pick simple best time for outdoor activity."""
    periods = {
        "morning": (6, 12),
        "afternoon": (12, 18),
        "evening": (18, 22),
    }

    scores = []

    for name, (start_hour, end_hour) in periods.items():
        period_rows = [
            row for row in rows
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
        snow_score = max_number([row.get("snowfall") for row in period_rows]) * 50
        comfort_penalty = abs(temperature - 18) * 2

        total_score = precipitation_score + comfort_penalty + wind_score * 0.5 + snow_score
        scores.append((total_score, name))

    if not scores:
        return "not recommended"

    score, name = min(scores)

    if score >= 85:
        return "not recommended"

    return name


def build_weather_context(
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

    clean_apparent_values = [
        value for value in (number_or_none(value) for value in apparent_values)
        if value is not None
    ]

    min_apparent = min(clean_apparent_values, default=None)
    max_apparent = max(clean_apparent_values, default=None)

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

    return {
        "day": day,
        "location": location.get("city"),
        "postal_code": location.get("postal_code"),
        "min_apparent_temperature": min_apparent,
        "max_apparent_temperature": max_apparent,
        "max_precipitation_probability": max_precipitation_probability,
        "max_snowfall": max_snowfall,
        "max_wind_gusts": max_wind_gusts,
        "feels_cold": feels_cold,
        "feels_hot": feels_hot,
        "rain_expected": rain_expected,
        "snow_expected": snow_expected,
        "windy": windy,
        "best_outdoor_time": best_outdoor_time(rows),
        "user_preferences": {
            "cold_sensitivity": preferences.get("cold_sensitivity"),
            "heat_sensitivity": preferences.get("heat_sensitivity"),
            "bad_weather_sensitivity": preferences.get("bad_weather_sensitivity"),
            "recommendation_style": preferences.get("recommendation_style"),
            "tone": preferences.get("tone"),
            "daytime_alerts": preferences.get("daytime_alerts"),
        },
    }


def available_forecast_dates(weather_json: dict[str, Any]) -> list[date]:
    dates = []

    for date_text in (weather_json.get("daily") or {}).get("time") or []:
        try:
            dates.append(date.fromisoformat(date_text))
        except (TypeError, ValueError):
            continue

    return dates


def dates_between(start_date: date, end_date: date) -> list[date]:
    days = (end_date - start_date).days

    if days < 0:
        return []

    return [start_date + timedelta(days=offset) for offset in range(days + 1)]


def user_preferences_context(preferences: dict[str, Any]) -> dict[str, Any]:
    return {
        "cold_sensitivity": preferences.get("cold_sensitivity"),
        "heat_sensitivity": preferences.get("heat_sensitivity"),
        "bad_weather_sensitivity": preferences.get("bad_weather_sensitivity"),
        "recommendation_style": preferences.get("recommendation_style"),
        "tone": preferences.get("tone"),
        "daytime_alerts": preferences.get("daytime_alerts"),
    }


def build_weather_period_context(
    weather_json: dict[str, Any],
    preferences: dict[str, Any],
    location: dict[str, Any],
    period: dict[str, Any],
) -> dict[str, Any]:
    period_type = period.get("type") or "today"
    start_date_text = period.get("start_date") or period.get("date")
    end_date_text = period.get("end_date") or period.get("date") or start_date_text

    if start_date_text is None or end_date_text is None:
        start_date = datetime.now(ZURICH_TZ).date()
        end_date = start_date
    else:
        start_date = date.fromisoformat(start_date_text)
        end_date = date.fromisoformat(end_date_text)

    forecast_dates = set(available_forecast_dates(weather_json))
    selected_dates = [
        forecast_date for forecast_date in dates_between(start_date, end_date)
        if forecast_date in forecast_dates
    ]

    daily_contexts = []

    for forecast_date in selected_dates:
        context = build_weather_context(
            weather_json,
            preferences,
            location,
            day=f"date:{forecast_date.isoformat()}",
        )
        context["date"] = forecast_date.isoformat()
        context["weekday"] = forecast_date.strftime("%A")
        daily_contexts.append(context)

    return {
        "location": location.get("city"),
        "postal_code": location.get("postal_code"),
        "period_type": period_type,
        "period_label": period.get("label"),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily_contexts": daily_contexts,
        "user_preferences": user_preferences_context(preferences),
    }
