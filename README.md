# ANW — Always Nice Weather ☀️

A Telegram bot that turns Swiss weather forecasts into simple, human daily advice.

## What is this?

ANW answers everyday weather questions so you don't have to read a forecast table. You save your Swiss location and a few preferences, then ask things like "Should I take an umbrella today?" or "What should I wear this weekend?" — and get a short, clear answer. It knows about Swiss postal codes, supports follow-up questions, and sends scheduled advice in the morning and evening if you want it.

## What can it do?

🗓 **Today and Tomorrow advice** — tap a button and get instant advice for your saved location.

🧭 **Ask wizard** — pick a location, time period, and topic (clothing, activities, general overview, or what to watch out for) through a simple step-by-step menu.

💬 **Free-text questions** — ask anything in plain English. Follow-up questions work too: "and in Luzern?", "what about this week?", "how about activities?".

🔔 **Smart notifications** — morning and evening scheduled advice, plus alerts when the forecast changes significantly. Positive changes (rain stopped, wind calmed) are included.

⚙️ **Personal preferences** — save your location, notification times, weather sensitivity, tone (formal / casual / humorous), and advice style (practical / activities / cozy).

## How does it work?

When you send a message, Python resolves the location and time period, then fetches the forecast from Open-Meteo. The structured forecast data is passed to an AI model through OpenRouter, which writes a short, human-readable answer. The AI only sees prepared context — it never touches the database or raw forecast JSON directly. This keeps the responses focused and prevents hallucination.

## Tech stack

- Python + aiogram (Telegram bot)
- PostgreSQL (user settings and forecast storage)
- Open-Meteo API (weather forecasts, free, no key needed)
- OpenRouter API (AI text generation)
- Deployed on Railway (or any platform supporting two processes)

## Project structure

**Bot**

| File | What it does |
| --- | --- |
| `main.py` | Telegram bot entry point. Handles Today, Tomorrow, Settings, Ask wizard, and free-text questions. |
| `onboarding.py` | Onboarding flow for location, notification times, sensitivities, tone, and alert preferences. |
| `keyboards.py` | Reply and inline keyboard builders. |

**Scheduler**

| File | What it does |
| --- | --- |
| `schedule.py` | Background entry point. Refreshes forecasts, sends scheduled advice, and sends weather change alerts. |

**Weather**

| File | What it does |
| --- | --- |
| `weather.py` | Fetches and stores Open-Meteo forecasts. Builds structured weather context for single-day and multi-day periods. |
| `weather_changes.py` | Compares old and new forecasts to detect negative and positive weather changes. |

**AI**

| File | What it does |
| --- | --- |
| `ai_advice.py` | Generates short daily advice from structured weather context. |
| `ai_chat.py` | Extracts intent from free-text questions and generates focused weather answers. |

**Data**

| File | What it does |
| --- | --- |
| `database.py` | PostgreSQL schema setup and query helpers. |
| `import_postal_codes.py` | One-off importer for Swiss postal codes from geo.admin.ch. |

**Config**

| File | What it does |
| --- | --- |
| `config.py` | Loads shared environment variables and constants. |
| `.env.example` | Template for required environment variables. |
| `requirements.txt` | Python dependencies. |

## Local setup

To run the bot locally, you'll need Python 3.11+, PostgreSQL, and API keys for Telegram and OpenRouter.

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Create `.env` from the example:

```powershell
Copy-Item .env.example .env
```

Fill in the required values:

```env
BOT_TOKEN=your_telegram_bot_token
OPENROUTER_API_KEY=your_openrouter_api_key
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/anw_weather_ai_bot
```

Optional:

```env
OPENROUTER_MODEL=openai/gpt-4o-mini
```

Import Swiss postal codes once (requires a running PostgreSQL database):

```powershell
python import_postal_codes.py
```

Run the bot and the scheduler as separate processes:

```powershell
python main.py
python schedule.py
```

## Environment variables

| Variable | Required | Used by | Purpose |
| --- | --- | --- | --- |
| `BOT_TOKEN` | Yes | `config.py`, `main.py`, `schedule.py` | Telegram bot token for aiogram. |
| `DATABASE_URL` | Yes | `config.py`, `database.py`, `import_postal_codes.py` | PostgreSQL connection string. |
| `OPENROUTER_API_KEY` | Yes for AI features | `ai_advice.py`, `ai_chat.py` | API key for OpenRouter chat completions. |
| `OPENROUTER_MODEL` | No | `ai_advice.py`, `ai_chat.py` | Optional OpenRouter model override. Defaults to `openai/gpt-4o-mini`. |

## Developer notes

- Run `main.py` and `schedule.py` as separate long-running processes — one handles Telegram, the other handles background refreshes and notifications.
- Forecasts are stored as raw JSON in PostgreSQL and converted to structured context before AI is called. AI never queries the database.
- Conversation history (last 6 messages per user) is stored in memory and resets on bot restart.
- Wizard state and onboarding sessions are also in memory only — they do not survive restarts.
- Run `import_postal_codes.py` once after creating the database. `setup_database()` does not populate postal codes.
- City search is accent-insensitive: "schupfheim" finds "Schüpfheim", "zurich" finds "Zürich".
- No automated tests currently.
