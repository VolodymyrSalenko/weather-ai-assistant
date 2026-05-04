"""Detect important forecast changes by comparing old and new structured Open-Meteo data."""

from typing import Any

from weather import hourly_rows_for_date, max_number, number_or_none


def forecast_facts(weather_json: dict[str, Any], day: str) -> dict[str, float | None]:
    rows = hourly_rows_for_date(weather_json, day)

    apparent_values = [
        value for value in (number_or_none(row.get("apparent_temperature")) for row in rows)
        if value is not None
    ]

    return {
        "max_precipitation_probability": max_number(
            [row.get("precipitation_probability") for row in rows],
        ),
        "max_snowfall": max_number([row.get("snowfall") for row in rows]),
        "max_wind_gusts_10m": max_number([row.get("wind_gusts_10m") for row in rows]),
        "max_apparent_temperature": max(apparent_values, default=None),
    }


def detect_weather_changes(
    old_weather_json: dict[str, Any],
    new_weather_json: dict[str, Any],
    day: str = "today",
    bad_weather_sensitivity: str = "medium",
) -> dict[str, Any]:
    old_facts = forecast_facts(old_weather_json, day)
    new_facts = forecast_facts(new_weather_json, day)
    changes = []

    rain_thresholds = {"high": 30, "medium": 50, "low": 70}
    rain_threshold = rain_thresholds.get(bad_weather_sensitivity, 50)

    if (
        old_facts["max_precipitation_probability"] < rain_threshold
        and new_facts["max_precipitation_probability"] >= rain_threshold
    ):
        changes.append("Rain becomes likely.")

    if old_facts["max_snowfall"] == 0 and new_facts["max_snowfall"] > 0:
        changes.append("Snow becomes likely.")

    if old_facts["max_wind_gusts_10m"] < 40 and new_facts["max_wind_gusts_10m"] >= 40:
        changes.append("Strong wind appears.")

    old_max_temperature = old_facts["max_apparent_temperature"]
    new_max_temperature = new_facts["max_apparent_temperature"]

    if (
        old_max_temperature is not None
        and new_max_temperature is not None
        and abs(old_max_temperature - new_max_temperature) >= 5
    ):
        changes.append("Big temperature change.")

    important_changes = []
    regular_changes = []

    for change in changes:
        if "Rain" in change:
            regular_changes.append(change)
        else:
            important_changes.append(change)

    # Positive changes — weather improving
    positive_changes = []

    rain_stopped_threshold = rain_threshold
    if (
        old_facts["max_precipitation_probability"] >= rain_stopped_threshold
        and new_facts["max_precipitation_probability"] < rain_stopped_threshold
    ):
        positive_changes.append("Rain has stopped.")

    old_temp = old_facts["max_apparent_temperature"]
    new_temp = new_facts["max_apparent_temperature"]
    if (
        old_temp is not None
        and new_temp is not None
        and not (14 <= old_temp <= 24)
        and 14 <= new_temp <= 24
    ):
        positive_changes.append("Temperature is now comfortable.")

    if (
        old_facts["max_wind_gusts_10m"] >= 40
        and new_facts["max_wind_gusts_10m"] < 40
    ):
        positive_changes.append("Wind has calmed down.")

    if old_facts["max_snowfall"] > 0 and new_facts["max_snowfall"] == 0:
        positive_changes.append("Snow has stopped.")

    any_negative = bool(important_changes or regular_changes)
    any_positive = bool(positive_changes)

    return {
        "important_change": any_negative or any_positive,
        "has_important_changes": bool(important_changes),
        "has_positive_changes": any_positive,
        "changes": changes,
        "important_changes": important_changes,
        "regular_changes": regular_changes,
        "positive_changes": positive_changes,
        "facts": {
            "old": old_facts,
            "new": new_facts,
        },
    }
