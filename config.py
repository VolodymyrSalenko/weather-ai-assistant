import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in .env")

ZURICH_TZ = ZoneInfo("Europe/Zurich")
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"