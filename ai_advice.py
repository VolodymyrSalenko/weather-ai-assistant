import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """
You are ANW, Always Nice Weather.
You do not show raw weather data.
You give simple daily advice based on weather and user preferences.
Use simple English, A2 level.
Keep it short: 2-4 sentences.
Be practical and friendly.
Respect tone and recommendation_style from user_preferences.
""".strip()


def generate_ai_advice(weather_context: dict[str, Any]) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set in .env")

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(weather_context, ensure_ascii=False),
            },
        ],
        "max_tokens": 180,
        "temperature": 0.7,
    }

    response = httpx.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()
    message = data["choices"][0]["message"]["content"]
    return str(message).strip()
