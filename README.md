# ANW - Always Nice Weather

ANW (Always Nice Weather) is a Telegram bot that will help users make better daily weather decisions. Instead of showing raw forecast data, the future product should turn trusted weather information into clear advice.

This repository is currently at the first working step: a minimal aiogram bot that responds to `/start`.

## Current Status

- Basic Telegram bot
- Reads `BOT_TOKEN` from `.env`
- Implements only `/start`
- No onboarding yet
- No weather API logic yet
- No AI logic yet
- No database yet

## Create `.env`

Create a `.env` file from the example:

```powershell
Copy-Item .env.example .env
```

Then add your Telegram bot token:

```env
BOT_TOKEN=your_telegram_bot_token_here
OPENROUTER_API_KEY=
```

## Install Dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run The Bot

```powershell
python main.py
```

## Available Commands

- `/start` - replies with a welcome message

## Product Direction

ANW should provide decisions, not raw weather data. Future versions will add onboarding, user preferences, trusted Swiss weather data, rule-based advice, AI-generated wording, persistent storage, and scheduled notifications.
