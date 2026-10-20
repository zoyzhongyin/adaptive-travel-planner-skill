---
name: flight-fare-watch
description: Monitor airfare across requested travel dates via FlyAI and GitHub Actions. Track reference-price thresholds, suppress duplicate alerts, and avoid routine ChatGPT token usage.
---

# Flight Fare Watch — Low-Token Fare Monitoring

Repository-local Codex Skill based on the verified FlyAI (Fliggy) domestic-flight interface. Monitoring features were informed by https://github.com/pavlo-kashko/flight-fare-tracker (MIT license): periodic checks, threshold/delta rules, and deduplication. The upstream SerpAPI implementation is not installed or needed because it requires a separate API key and its TFU/AAT coverage is unverified.

## Installed components

- GitHub Actions: .github/workflows/altay-fare-watch.yml
- Monitor: scripts/flight_price_watch.py
- Provider: existing FlyAI CLI, deployed into each GitHub Actions run rather than the restricted Codex cloud shell
- User-controlled configuration: flight-watch/config.json
- Durable notification state: flight-watch/state.json, updated via GitHub Contents API only for a confirmed new qualifying alert
- Results: workflow Summary and flight-watch-check artifact (5-day retention)
- NOTE: GitHub Issues is disabled for this fork (HTTP 410), so the Issue-based notification plan is unsupported. A new qualifying low fare instead triggers a deliberately failed GitHub Actions run. The user must configure GitHub Actions failure notifications to receive a push/email.
- Automatic runs never invoke a ChatGPT model, so normal monitoring consumes 0 ChatGPT model tokens.

## Current query and alert rules

- Route: TFU ↔ AAT, 5 nights, 4 complete ski days.
- Candidate outbound dates: Dec 5, Dec 14, Dec 23, 2026, each returning five days later. These are based on a tentative 3-on/6-off work shift pattern and are NOT a confirmed December schedule.
- Frequency: every 30 minutes, rotating one outbound/return pair per run; each date pair is nominally checked every 90 minutes. GitHub Actions scheduled runs may be delayed or dropped.
- Both direct legs must have a usable ticketPrice reference fare; notify to CHECK actual bookability if the sum is at most CNY 1500 (ideal price CNY 1200).
- Suppress repeats unless that pair's already alerted lowest quote drops at least CNY 50 or crosses into the ideal band.
- ticketPrice is NOT confirmed all-in cost: tax, check-in baggage and ski-equipment costs require a logged-in checkout.
- API errors, empty trial-mode results and a status=1 message mean missing data, not no flights.
- No booking or payment ever. Do not attempt to evade access rules or rate controls.

## How to use from ChatGPT

Read and edit flight-watch/config.json through the connected GitHub tools. To stop monitoring, set enabled=false. Do not overwrite the saved work-rest dates without confirmation of the user's official roster. Do not rely on a Codex-side npm install. To view current status, use GitHub Actions latest Altay Fare Watch run; a SUCCESS run means no new qualifying alert, not necessarily a valid price, and a FAILED run should be inspected for the expected price-alert marker versus a program failure.

If the user wants more frequent scans, explain GitHub's theoretical minimum 5-minute cron and best-effort scheduling and the unverified rate capacity of FlyAI's free trial API. Never guarantee real-time notifications or switch to high-frequency scraping without assessing rate limits. For a reliable faster service, connect a suitable explicitly quota-approved official source.

## Test

The command python3 scripts/flight_price_watch.py --test exercises the watcher with simulated prices, no live flight lookup or persistent state writes.
