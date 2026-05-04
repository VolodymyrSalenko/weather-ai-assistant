# Triage Log

A record of technical hurdles encountered during development of ANW
(Always Nice Weather) and how each was resolved.

---

## 1. AI chat losing conversation state on typos

**Problem:** When the bot asked a clarifying question (e.g. "Which
day?") and the user replied with a typo like "Tommorow", the bot
responded with "I can help only with weather and daily planning."
instead of understanding the answer.

**Root cause:** The `merge_pending_intent` function silently deleted
the user's pending state when `parse_day_reply` could not match the
input. The user's reply was then treated as a brand new unrelated
message.

**Solution:** Replaced the silent state deletion with a user-friendly
error message that preserves the state. The bot now replies "I didn't
catch the day. Try: today, tomorrow, this weekend, or a date like
2026-05-03." and waits for a new answer without losing context.

---

## 2. AI not understanding follow-up questions

**Problem:** After receiving a weather answer for Ebikon, the user
wrote "and in Luzern" and the bot did not understand it was a
follow-up question about the same topic in a different city.

**Root cause:** Each message was processed independently with no
memory of previous exchanges. The AI received only the current
message without any context.

**Solution:** Implemented in-memory conversation history (last 6
messages per user). History is passed to the AI intent extractor
so it can resolve follow-up questions like "and in Luzern" or
"what about this week?" by reading previous context.

---

## 3. AI getting stuck in clarification loop

**Problem:** When a user asked "how long rain in Basel" and then
answered "this week", the bot kept asking "Which specific day this
week?" in an infinite loop instead of answering.

**Root cause:** Two bugs found via debug logging:
1. Python forced `needs_clarification = True` whenever
   `time_period.type` was "unknown", overriding the AI's own
   decision.
2. The AI prompt did not explain that "week" and "weekend" are
   complete valid answers — the AI kept asking for a specific day.

**Solution:** Changed Python logic to only force clarification when
the AI also requested it. Added an explicit instruction to the
`INTENT_SYSTEM_PROMPT`: multi-day periods (week, weekend) are
complete answers and must not trigger further clarification.

---

## 4. Swiss postal codes not recognized as weather queries

**Problem:** When a user typed "8050" (a valid Swiss postal code),
the bot replied "I can help only with weather and daily planning."
instead of showing weather for that location.

**Root cause:** The AI intent extractor did not know that a 4-digit
number could be a Swiss postal code. It classified the input as
non-weather.

**Solution:** Added an explicit rule to `INTENT_SYSTEM_PROMPT`:
"A 4-digit number is a Swiss postal code and counts as a location."

---

## 5. City search failing for names with umlauts

**Problem:** Searching for "schupfheim" (without umlaut) returned
no results, while "schüpfheim" (with umlaut) worked correctly.
Users without a German keyboard could not find Swiss cities.

**Root cause:** The SQL query used a plain `ILIKE` comparison which
is accent-sensitive. "u" and "ü" were treated as different characters.

**Solution:** Installed the PostgreSQL `unaccent` extension and
updated the search query to use `unaccent(lower(city)) ILIKE
unaccent(lower(%s))` for accent-insensitive matching.

---

## 6. Bot showing wrong error for dates beyond 7-day forecast

**Problem:** When a user selected a date more than 7 days ahead in
the Ask wizard, the bot replied "I can help only with weather and
daily planning." — a confusing and misleading error message.

**Root cause:** Open-Meteo only provides 7-day forecasts. When the
date was out of range, `build_weather_period_context` returned empty
context, and the AI interpreted the empty weather data as a
non-weather request.

**Solution:** Added date range validation before fetching weather.
The bot now replies "I can only forecast up to 7 days ahead. Please
pick a date within the next week." and the Ask wizard prompt was
updated to mention the 7-day limit upfront.

---

## 7. Deployment failure: postal_codes table missing

**Problem:** After deploying to Railway, the bot crashed immediately
with `psycopg.errors.UndefinedTable: relation "postal_codes" does
not exist`.

**Root cause:** The `postal_codes` table is not created by
`setup_database()` — it requires a separate one-time import script
(`import_postal_codes.py`) that downloads data from geo.admin.ch.
This script had not been run on the production database.

**Solution:** Added `import_postal_codes.py` as a pre-deploy step
in Railway settings. It now runs automatically before each
deployment, creating and populating the table if it does not exist.

---

## 8. User preferences (tone, style) ignored in AI answers

**Problem:** Users who set tone="humorous" or
recommendation_style="activities" received the same style of
answers as everyone else. The preferences were saved but not used.

**Root cause:** The `ANSWER_SYSTEM_PROMPT` in `ai_chat.py` had no
instructions about how to use `user_preferences` from the weather
context. The AI received the preferences but did not know what to
do with them.

**Solution:** Added explicit tone and style instructions to
`ANSWER_SYSTEM_PROMPT`: formal/casual/humorous tone rules and
practical/activities/cozy_fun recommendation style rules.

---

## 9. Weather change alerts not respecting user sensitivity

**Problem:** All users received rain alerts at the same 50%
probability threshold regardless of their `bad_weather_sensitivity`
setting.

**Root cause:** The rain threshold in `detect_weather_changes` was
hardcoded to 50%. The function had no access to user preferences.

**Solution:** Added `bad_weather_sensitivity` parameter to
`detect_weather_changes`. Thresholds are now 30% for high
sensitivity, 50% for medium, and 70% for low. Each user's alert
is evaluated with their own threshold.

---

## 10. Scheduler running as single process on Railway

**Problem:** After initial deployment, only `main.py` was running.
The scheduler (`schedule.py`) was not running, meaning no automatic
weather updates, no morning/evening notifications, and no change
alerts.

**Root cause:** Railway deployed only one process from the
repository. The `Procfile` was not present, so Railway did not
know about the second process.

**Solution:** Added a `Procfile` to the repository defining both
processes. Created a second Railway service pointing to the same
repository with `python schedule.py` as the custom start command.
