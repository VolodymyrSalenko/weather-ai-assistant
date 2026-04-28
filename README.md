# ANW - Always Nice Weather

ANW (Always Nice Weather) is a Telegram bot that will help users make better daily weather decisions. Instead of showing raw forecast data, the future product should turn trusted weather information into clear advice.

This repository is currently at the second working step: a minimal aiogram bot with an in-memory onboarding preferences flow.

## Current Status

- Basic Telegram bot with onboarding
- Reads `BOT_TOKEN` from `.env`
- Implements `/start`, `/reset`, and `/debug`
- Stores user preferences in memory while the bot process is running
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

- `/start` - starts onboarding if preferences are not completed
- `/reset` - clears your in-memory preferences and starts onboarding again
- `/debug` - shows current onboarding state and saved in-memory preferences

## Onboarding

The bot asks for:

- Swiss postal code
- morning notification time
- evening notification time
- quiet hours
- cold sensitivity
- heat sensitivity
- bad weather sensitivity
- recommendation style
- tone of voice
- daytime weather change alerts

Preferences are stored only in memory for now. They disappear when the bot process stops.

## Product Direction

ANW should provide decisions, not raw weather data. Future versions will add onboarding, user preferences, trusted Swiss weather data, rule-based advice, AI-generated wording, persistent storage, and scheduled notifications.
