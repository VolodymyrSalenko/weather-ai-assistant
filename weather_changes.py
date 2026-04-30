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
) -> dict[str, Any]:
    old_facts = forecast_facts(old_weather_json, day)
    new_facts = forecast_facts(new_weather_json, day)
    changes = []

    if (
        old_facts["max_precipitation_probability"] < 50
        and new_facts["max_precipitation_probability"] >= 50
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

    return {
        "important_change": bool(changes),
        "changes": changes,
        "facts": {
            "old": old_facts,
            "new": new_facts,
        },
    }
