---
name: flight-search
description: Search Google Flights for prices, times, and airlines. No API key required.
homepage: https://github.com/Olafs-World/flight-search
metadata:
  {
    "openclaw":
      {
        "emoji": "✈️",
        "requires": { "bins": ["uvx"] },
        "install":
          [
            {
              "id": "uv",
              "kind": "pip",
              "package": "uv",
              "bins": ["uvx"],
              "label": "Install uv (for uvx)",
            },
          ],
      },
  }
---

## China flights: network-resistant execution (priority override)

For China domestic routes such as TFU ↔ AAT, do not make package installation a prerequisite for answering. First use the connected assistant's **already available browser/web search tools** and date-specific carrier/OTA results when those tools are available. The `uvx flight-search` command below is an optional enhancement, not mandatory. Never treat a published route-page lowest fare as a date-specific bookable quote.

If `uvx` exists but package download fails (PyPI DNS/connectivity, blocked internet, SSL error, timeout), **do not retry the same package install repeatedly**. Immediately switch to the following browser-only workflow; do not claim the CLI executed or that prices were scraped:

1. Compare the user's exact requested dates using flight search pages that allow date filters (first airline direct sites Spring Airlines and Sichuan Airlines; then Ctrip/Trip.com, Qunar, Google Flights or Skyscanner as coverage permits). Use the real 2026 dates and route `TFU → AAT → TFU`; check `CTU` separately if useful.
2. Search outbound and inbound legs independently when round-trip search pages are inaccessible, but never add generic teaser fares and present the sum as a bookable quote. A verified amount requires **date-specific selectable inventory**, per-person taxes and fees, same currency, route, itinerary, and observation time.
3. Look for airport mismatch, overnight layovers, flight time changes, ski-equipment allowance, prepaid hold baggage, ski board dimensions/fees, and winter-weather disruption risks. Direct flight is preferred over overnight/Urumqi transfer for a short ski trip unless meaningful savings are verified.
4. Show a compact comparison: dates, exact flight/airports/stops, fare (RMB per person round trip where actually verified), baggage/ski-gear costs, and evidence/link/time. If any price cannot be verified write `未核实`; cite the source of each flight/schedule detail and flag advertised `¥XXX起` as **not an actual price for these dates**.
5. If web sources cannot expose the dynamic booking page, clearly explain that quote data is unavailable. Give the user ready-to-open official booking entry points and say which date pairs to check. Never suggest that a failed CLI run proves the route has no flights.

For the user's Altay ski vacation: evaluate **2026-12-08 → 2026-12-13**, **2026-12-09 → 2026-12-14**, **2026-12-10 → 2026-12-15** and adjacent pairs yielding four full skiing days; default to one adult economy traveler unless another party size is supplied. Avoid booking without explicit separate approval.

# Flight Search

Search Google Flights from the command line. Get prices, times, and airlines - no API key needed.

Built on [fast-flights](https://github.com/AWeirdDev/flights).

## Quick Start

```bash
# one-off search (no install needed)
uvx flight-search DEN LAX --date 2026-03-01

# or install globally
uv tool install flight-search
flight-search JFK LHR --date 2026-06-15 --return 2026-06-22
```

## Options

```
positional arguments:
  origin                Origin airport code (e.g., DEN, LAX, JFK)
  destination           Destination airport code

options:
  --date, -d            Departure date (YYYY-MM-DD) [required]
  --return, -r          Return date for round trips (YYYY-MM-DD)
  --adults, -a          Number of adults (default: 1)
  --children, -c        Number of children (default: 0)
  --class, -C           Seat class: economy, premium-economy, business, first
  --limit, -l           Max results (default: 10)
  --output, -o          Output format: text or json (default: text)
```

## Examples

```bash
# One-way flight
flight-search DEN LAX --date 2026-03-01

# Round trip with passengers
flight-search JFK LHR --date 2026-06-15 --return 2026-06-22 --adults 2

# Business class
flight-search SFO NRT --date 2026-04-01 --class business

# JSON output for parsing
flight-search ORD CDG --date 2026-05-01 --output json
```

## Example Output

```
✈️  DEN → LAX
   One way · 2026-03-01
   Prices are currently: typical

──────────────────────────────────────────────────
   Frontier ⭐ BEST
   🕐 10:43 PM → 12:30 AM +1
   ⏱️  2 hr 47 min
   ✅ Nonstop
   💰 $84

──────────────────────────────────────────────────
   United ⭐ BEST
   🕐 5:33 PM → 7:13 PM
   ⏱️  2 hr 40 min
   ✅ Nonstop
   💰 $139
```

## JSON Output

Returns structured data:

```json
{
  "origin": "DEN",
  "destination": "LAX",
  "date": "2026-03-01",
  "current_price": "typical",
  "flights": [
    {
      "airline": "Frontier",
      "departure_time": "10:43 PM",
      "arrival_time": "12:30 AM",
      "duration": "2 hr 47 min",
      "stops": 0,
      "price": 84,
      "is_best": true
    }
  ]
}
```

## Links

- [PyPI](https://pypi.org/project/flight-search/)
- [GitHub](https://github.com/Olafs-World/flight-search)


## Mainland China airfare verification and ski-trip workflow

This skill is installed in a travel-planning Codex repository, sourced from https://github.com/Olafs-World/flight-search under the MIT license. Executable CLI package is not bundled. The repo-local SKILL.md only supplies instructions; live queries require uvx or the flight-search package installed in the Codex execution environment and network access to Google Flights.

For a Chengdu -> Altay ski trip:
1. Search **TFU** (Chengdu Tianfu) to **AAT** (Altay Xuedu) for each desired outbound and return date combination. If needed, search **CTU** (Shuangliu) separately, but never conflate city code CTU with the Tianfu airport TFU.
2. Prefer direct flights. Compare departure dates near Dec 7-11, 2026 and return dates 4-5 calendar days after departure (5-6 total calendar days), ensuring at least four on-slope days if feasible.
3. Run a real query, for example: `uvx flight-search TFU AAT --date 2026-12-08 --return 2026-12-14 --output json`. If uvx is missing, request permission to install uv/flight-search; do not claim live search succeeded.
4. Compare **bookable, date-specific, round-trip total fares** only in the same currency; verify luggage allowance, ski equipment/bag charges, airport, times, routing, and refund rules. Do not confuse a carrier's generic advertised starting fare with the user's dates.
5. Treat Google Flights scraping as fallible: CAPTCHA, regional access limits, or missing mainland-China domestic inventory may cause incomplete results. Cross-check at least one Chinese OTA or airline booking site (Spring Airlines, Sichuan Airlines, Trip.com/Ctrip) before recommending any purchase.
6. Present a compact matrix: outbound/return dates, airlines and routing, departure/arrival times, **all-in price in CNY if actually verified**, baggage and ski gear fees, direct vs via Urumqi; identify the source and observation date. Write `unverified` for missing live numbers; never fabricate prices or invent discounts.
7. Do not purchase tickets or transmit payment/personal information without an explicit separate user request and a supported safe booking workflow.

Remember: a Skill is not a ticketing API, price feed, or background scheduler; this installation alone does not continuously monitor or alert on fares.
