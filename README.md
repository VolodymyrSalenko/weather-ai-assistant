# ANW - Always Nice Weather

ANW (Always Nice Weather) is a Telegram bot that turns Swiss weather forecasts into short, practical daily advice. It stores user settings, fetches 7-day forecasts from Open-Meteo, keeps forecasts fresh in PostgreSQL, and uses OpenRouter to write friendly user-facing messages.

The project is built as a small Python application with two runnable processes:

- `main.py` runs the Telegram bot for onboarding, manual weather advice, settings, and free-text weather questions.
- `schedule.py` runs background weather refreshes, scheduled daily advice messages, and weather change alerts.

## Purpose

The main goal is to help users make simple daily decisions without reading raw weather tables. Users save a Swiss location and preference profile, then ANW can answer questions like:

- Should I take an umbrella today?
- Can I wear this tomorrow?
- What should I know about the weekend?
- When is a good time to go outside?

AI is used only after Python has resolved the user, location, date range, and weather context. The AI modules do not access PostgreSQL directly.

## Architecture Overview

The application has four main layers:

1. Telegram interface
   - `main.py`, `onboarding.py`, and `keyboards.py` handle aiogram routing, user messages, reply keyboards, inline buttons, and onboarding.

2. Data layer
   - `database.py` owns PostgreSQL schema setup and helper functions for users, preferences, postal codes, weather forecasts, and notification logs.
   - `import_postal_codes.py` imports Swiss postal code data into the `postal_codes` table from geo.admin.ch.

3. Weather layer
   - `weather.py` fetches raw Open-Meteo forecasts, stores them, loads stored forecasts, and builds structured weather context.
   - `weather_changes.py` compares old and new forecasts to detect important changes.

4. AI layer
   - `ai_advice.py` generates short daily advice from structured weather context.
   - `ai_chat.py` understands free-text weather questions and generates answers from prepared context.

## Project Files

| File | Role |
| --- | --- |
| `main.py` | Main Telegram bot entry point. Starts database setup, registers onboarding router, handles Today, Tomorrow, Settings, Ask, and free-text weather questions. |
| `schedule.py` | Background scheduler entry point. Refreshes weather, sends scheduled morning/evening messages, sends weather change alerts, and cleans old forecasts. |
| `database.py` | PostgreSQL table creation and query helpers for users, preferences, forecasts, notifications, and postal code lookup. |
| `weather.py` | Open-Meteo integration and weather context builder for single-day and multi-day periods. |
| `weather_changes.py` | Detects important changes such as likely rain, snow, strong wind, or large apparent temperature changes. |
| `ai_advice.py` | OpenRouter helper for short daily advice messages. |
| `ai_chat.py` | OpenRouter helper for intent extraction and free-text weather question answers. |
| `onboarding.py` | aiogram onboarding flow for collecting location, notification times, quiet hours, sensitivities, advice style, tone, and alert settings. |
| `keyboards.py` | Telegram reply and inline keyboard builders. |
| `config.py` | Loads required shared environment variables and timezone/service constants. |
| `import_postal_codes.py` | One-off importer for Swiss postal codes from the official geo.admin.ch source. |
| `requirements.txt` | Python dependencies. |
| `.env.example` | Example environment file. |

There are no application subfolders at the moment; the Python modules live in the repository root.

## Main Module Connections

`main.py`:

- reads `BOT_TOKEN` from `config.py`;
- calls `setup_database()` from `database.py`;
- includes the onboarding router from `onboarding.py`;
- uses `keyboards.py` for persistent menu and inline buttons;
- uses `weather.py` to load or fetch stored forecasts and build weather context;
- uses `ai_advice.py` for Today/Tomorrow advice;
- uses `ai_chat.py` for Ask and free-text weather questions.

`schedule.py`:

- calls `setup_database()` before starting loops;
- refreshes active postal code forecasts every 2 hours;
- refreshes all postal code forecasts once per day at 03:00 Europe/Zurich;
- checks completed user preferences every minute for morning and evening notification times;
- respects quiet hours and notification logs;
- uses `weather_changes.py` to detect important changes for today's forecast.

`database.py`:

- creates `users`, `preferences`, `weather_forecasts`, and `notification_log`;
- expects `postal_codes` to exist after running `import_postal_codes.py`;
- stores raw Open-Meteo JSON in `weather_forecasts`;
- uses `notification_log` to prevent duplicate scheduled and change-alert messages.

## Entry Points

Run the Telegram bot:

```powershell
python main.py
```

Run the scheduler in a separate terminal/process:

```powershell
python schedule.py
```

Import Swiss postal codes before using onboarding or city search:

```powershell
python import_postal_codes.py
```

## Bot Commands and Menu

- `/start` creates or loads the user and starts onboarding if settings are missing.
- `/reset` deletes saved settings and starts the same onboarding flow again.
- `Today` generates advice for today.
- `Tomorrow` generates advice for tomorrow.
- `Settings` shows the saved preference profile and a `Change settings` button.
- `Ask` shows example weather questions; normal text messages are also handled as weather questions after onboarding.

## Local Setup

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

`OPENROUTER_MODEL` is read by `ai_advice.py` and `ai_chat.py`. If it is missing, both modules default to `openai/gpt-4o-mini`. This optional variable is not currently listed in `.env.example`.

## Environment Variables

| Variable | Required | Used by | Purpose |
| --- | --- | --- | --- |
| `BOT_TOKEN` | Yes | `config.py`, `main.py`, `schedule.py` | Telegram bot token for aiogram. |
| `DATABASE_URL` | Yes | `config.py`, `database.py`, `import_postal_codes.py` | PostgreSQL connection string. |
| `OPENROUTER_API_KEY` | Yes for AI features | `ai_advice.py`, `ai_chat.py` | API key for OpenRouter chat completions. |
| `OPENROUTER_MODEL` | No | `ai_advice.py`, `ai_chat.py` | Optional OpenRouter model override. Defaults to `openai/gpt-4o-mini`. |

## Database Setup

The code creates most application tables automatically when `main.py` or `schedule.py` starts:

- `users`
- `preferences`
- `weather_forecasts`
- `notification_log`

The `postal_codes` table is different. It is created and populated by:

```powershell
python import_postal_codes.py
```

This importer downloads an official Swiss postal code CSV ZIP from geo.admin.ch. The PostgreSQL database itself must already exist and be reachable through `DATABASE_URL`; this repository does not include a Docker Compose file or database creation script.

## Core Logic Walkthrough

1. A user sends `/start`.
2. `main.py` routes the message through `onboarding.py`.
3. The bot upserts the Telegram user in PostgreSQL.
4. If completed settings exist, the persistent main menu appears.
5. If no settings exist, onboarding asks for location, notification times, quiet hours, sensitivity settings, advice style, tone, and daytime alert preference.
6. Completed settings are saved in PostgreSQL.
7. The main menu shows four buttons: `Today`, `Tomorrow`, `Settings`, and `Ask`.

For Today or Tomorrow:

1. `main.py` loads the user's completed settings.
2. `weather.py` checks for today's stored Open-Meteo forecast for the saved postal code.
3. If no stored forecast exists, it fetches and saves a new 7-day forecast.
4. `weather.py` builds structured weather context for today or tomorrow.
5. `ai_advice.py` sends that context to OpenRouter.
6. The bot sends a short message with a location/date header and AI-generated advice.

For Ask or free-text questions:

1. `ai_chat.py` asks OpenRouter to understand the weather intent, location, and time period.
2. `main.py` resolves the location using `postal_codes` or the user's saved location.
3. `main.py` supports simple in-memory clarification state for missing location or day.
4. `weather.py` builds single-day or multi-day weather context.
5. `ai_chat.py` answers using only the prepared weather context.
6. The bot sends the answer with a location/date or date-range header.

For scheduled behavior:

1. `schedule.py` updates active locations once on startup.
2. It updates active locations every 2 hours.
3. It updates all postal code locations once per day at 03:00 Europe/Zurich.
4. It checks every minute for users whose `morning_time` or `evening_time` matches the current Europe/Zurich minute.
5. It skips quiet hours and uses `notification_log` to avoid duplicates.
6. It detects important weather changes for today and can send daytime change alerts when enabled.
7. It deletes old weather forecasts after updates using a 14-day cleanup window.

## External Services

- Telegram Bot API through `aiogram`
- PostgreSQL through `psycopg`
- Open-Meteo forecast API through `httpx`
- OpenRouter chat completions API through `httpx`
- geo.admin.ch postal code source for the importer

## Developer Notes

- Run `main.py` and `schedule.py` as separate long-running processes if you want both manual bot interactions and scheduled notifications.
- Forecasts are stored as raw JSON in PostgreSQL and converted into structured context before AI is called.
- The AI modules receive prepared context and should not query the database directly.
- Onboarding sessions and chat clarification state are in memory. They are not persisted across process restarts.
- `setup_database()` does not populate postal codes. Run `import_postal_codes.py` after creating the database.
- No automated test suite is currently present in the repository.
- No Docker Compose file is currently present for PostgreSQL.
