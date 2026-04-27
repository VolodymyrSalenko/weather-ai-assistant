# ANW - Always Nice Weather

ANW is a Telegram bot that will help users make better daily weather decisions. This first step only starts the bot and responds to `/start`.

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

## Install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run the bot

```powershell
python main.py
```

## Available commands

- `/start` - replies with a welcome message
