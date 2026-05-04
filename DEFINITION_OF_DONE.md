# Definition of Done

Progress tracker for ANW (Always Nice Weather) — a Telegram bot
that turns Swiss weather forecasts into simple daily advice.

---

## Core Features

- [x] User onboarding flow (location, notification times, quiet
      hours, sensitivities, tone, advice style)
- [x] Today and Tomorrow weather advice buttons
- [x] Ask wizard (location → period → category, 3-step guided flow)
- [x] Free-text weather questions in plain English
- [x] Conversation history for follow-up questions
- [x] Settings page with Change settings button
- [x] /start and /reset commands

## Weather Data

- [x] Open-Meteo 7-day forecast integration
- [x] Forecast stored in PostgreSQL as raw JSON
- [x] Automatic forecast refresh every 2 hours for active locations
- [x] Full Swiss postal code database imported from geo.admin.ch
- [x] Accent-insensitive city search (schupfheim finds Schüpfheim)
- [x] Swiss postal code recognition (4-digit number as location)
- [x] 7-day forecast limit validation with clear user message

## Notifications

- [x] Scheduled morning advice (today's weather)
- [x] Scheduled evening advice (tomorrow's weather)
- [x] Weather change alerts for negative changes (rain, snow, wind,
      temperature drop)
- [x] Weather change alerts for positive changes (rain stopped,
      wind calmed, temperature comfortable)
- [x] Per-user sensitivity thresholds for rain alerts
- [x] Quiet hours respected for all notifications
- [x] Duplicate notification prevention
- [x] "all" users receive alerts every 2 hours
- [x] "important" users receive critical alerts once per day

## AI Quality

- [x] Intent extraction with conversation history context
- [x] Multi-day periods (week, weekend) handled without clarification
- [x] Tone respected in answers (formal / casual / humorous)
- [x] Recommendation style respected (practical / activities /
      cozy_fun)
- [x] Safety rules against prompt injection
- [x] Non-weather questions rejected gracefully
- [x] Positive/negative change_type in weather change notifications

## Code Quality

- [x] Separation of concerns: Telegram / Weather / AI / Data layers
- [x] AI never queries PostgreSQL directly
- [x] Rate limiting (10 seconds between requests per user)
- [x] Error handling for all external API calls
- [x] In-memory conversation history (resets on restart)
- [x] Structured logging

## Deployment

- [x] Deployed on Railway (free tier)
- [x] Two separate processes: bot + scheduler
- [x] PostgreSQL on Railway
- [x] Environment variables configured
- [x] Pre-deploy step runs import_postal_codes.py automatically
- [x] unaccent PostgreSQL extension installed
- [x] Auto-deploy on git push (connected to GitHub)

## Documentation

- [x] README with friendly introduction and technical docs
- [x] Triage Log with real problems and solutions
- [x] Definition of Done (this file)
- [x] .env.example with comments

## Known Limitations

- [ ] No automated test suite
- [ ] Conversation history resets on bot restart (in-memory only)
- [ ] Full Swiss postal code update runs daily (all ~4000 locations)
- [ ] No Docker Compose file for local PostgreSQL setup
- [ ] unaccent extension must be created manually on new databases
