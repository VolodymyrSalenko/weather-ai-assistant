# ANW — Always Nice Weather (weather-ai-assistant)

ANW (Always Nice Weather) is an AI-powered Telegram bot that converts weather data into simple, actionable recommendations.

Instead of presenting raw forecasts such as temperature, precipitation probability, or wind speed, the system tells users what to do: what to wear, what to take, and how to plan their day.

---

## Overview

Weather data is widely available, but it requires interpretation. Most users either forget to check forecasts or do not translate the data into practical decisions.

ANW eliminates this step by delivering clear, timely, and personalized recommendations directly to the user.

The system acts as a lightweight assistant that:
- provides daily guidance
- sends proactive reminders
- suggests activities based on weather conditions

---

## Problem

Existing weather applications focus on data, not decisions.

In practice:
- users forget to check the weather
- users make poor decisions despite having access to forecasts
- weather impact on daily plans is underestimated

This leads to:
- discomfort (wrong clothing, missing items)
- inefficient planning
- missed opportunities

---

## Solution

ANW provides:
- proactive notifications (morning and evening)
- event-based alerts (weather changes)
- personalized recommendations
- natural language interaction via chat

The system removes the need to manually check and interpret weather data.

---

## Scope

- Geographic focus: Switzerland
- Location identification: ZIP / postal codes
- Multi-language input supported via Telegram
- Notifications are delivered in English

---

## Features (MVP)

### Onboarding

Users provide preferences during initial setup:
- locations (up to 3 ZIP codes)
- notification times
- sensitivity to weather conditions
- communication style

### Daily Notifications

- Morning: plan for the current day
- Evening: overview for the next day

### Event-Based Alerts

Triggered only when relevant:
- rain timing changes
- temperature drops
- strong wind

### Chat Interaction

Users can ask:
- what to wear
- whether it will rain
- if conditions are suitable for activities

---

## User Experience

The Telegram interface includes:
- chat input for natural interaction
- "Preferences" for updating settings
- "Quick Requests" for common actions

---

## Personalization

The system adapts to each user based on:
- selected locations
- weather sensitivity (temperature, rain, wind)
- preferred tone of voice (formal, casual, humorous)
- notification frequency

---

## Architecture


## System Flow

1. Fetch weather data
2. Normalize and store data
3. Detect significant changes
4. Generate insights
5. Produce natural language output
6. Send notifications

---

## Design Principles

- Provide decisions, not data
- Minimize user effort
- Deliver information at the right time
- Avoid redundant notifications

---

## Future Improvements

- advanced weekly location scheduling
- deeper personalization
- richer activity recommendations
- expanded weather sources

---

## Status

MVP in development
