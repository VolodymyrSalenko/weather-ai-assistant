"""Generate short daily weather advice through OpenRouter from structured weather context."""

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
Write a warm daily weather ritual, not a weather report.
Use simple English, A2-B1 level.
Keep it short: 2-4 sentences.
Start with the mood of the day.
Give one clear practical suggestion.
If possible, suggest the best time to go outside.
Do not show raw weather numbers.
Do not mention JSON, forecast data, or technical terms.
Never invent weather facts. Use only weather_context.
Respect user_preferences strongly.
Tone rules: formal is polite and calm; casual is simple and friendly; humorous is light humor, but not silly.
Recommendation style rules: practical focuses on clothes, items, and planning; activities suggests a simple activity if weather allows; cozy_fun suggests a cozy or pleasant idea if weather is not good.
If weather_context contains change_type, adapt the message:
- change_type "negative": warn the user clearly about the change. Give one practical suggestion (umbrella, jacket, stay inside). Be helpful but not alarming.
- change_type "positive": be upbeat and encouraging. The weather improved — suggest going outside or doing something pleasant. Match the recommendation_style: activities suggests a specific outdoor activity; cozy_fun suggests something enjoyable outside; practical suggests the best time to go out.
If change_type is not provided, write a normal daily weather ritual as usual.
Avoid generic phrases like "Enjoy your day", repeated advice, and claims not supported by weather_context.
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
