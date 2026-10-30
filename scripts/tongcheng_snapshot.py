#!/usr/bin/env python3
"""Read-only, low-frequency supplemental public-listing fare snapshot.

This is NOT a ticket inventory API. Only normal Chromium visits to public
Tongcheng booking pages, with no CAPTCHA bypass, stealth, account auth,
undocumented API requests or price-alert side effects. A 0/empty/errors
result always means DATA GAP, never 'no flight' or an over-budget result.

Never treat an unverified public-listing fare as a purchase-ready price.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlparse

BJT = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "flight-watch/config.json"
OUTPUT = ROOT / "flight-watch/tongcheng-latest.json"
CARRIERS = {"CA": "国航", "3U": "川航", "9C": "春秋"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
JS = r"""() => {
  const s = window.__NUXT__ && window.__NUXT__.state && window.__NUXT__.state.book1;
  const flights = s && Array.isArray(s.flightLists) ? s.flightLists : [];
  return flights.slice(0, 200).map(x => ({
    no: String(x.flightNo || '').slice(0,20),
    airline_code: String(x.airCompanyCode || '').slice(0,5),
    airport_dep: String(x.originAirportCode || '').slice(0,8),
    airport_arr: String(x.arriveAirportCode || '').slice(0,8),
    date: String(x.flyOffTime || '').slice(0,10),
    stops: x.stopNum,
    fare: x.flightPrice
  }));
}"""

def price(value):
    """Accept a positive finite decimal, rejecting boolean, currency strings and 0."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        d = Decimal(str(value))
        return d if d.is_finite() and Decimal("0") < d < Decimal("100000") else None
    except (InvalidOperation, ValueError):
        return None

def valid_fare(item: dict, *, origin: str, destination: str, day: str):
    if not isinstance(item, dict):
        return None
    number = str(item.get("no") or "").upper()
    carrier = number[:2]
    if not re.fullmatch(r"(?:9C|3U|CA)\d{3,5}", number):
        return None
    if carrier not in CARRIERS or str(item.get("airline_code") or "").upper() != carrier:
        return None
    if (item.get("airport_dep") != origin or item.get("airport_arr") != destination
            or item.get("date") != day or item.get("stops") not in (0, 0.0, "0")):
        return None
    amount = price(item.get("fare"))
    if amount is None:
        return None
    return {
        "flight": number,
        "airline": CARRIERS[carrier],
        "carrier": carrier,
        "price_cny": str(amount),
    }

def cheapest(items: list, *, origin: str, destination: str, day: str):
    usable = [valid_fare(x, origin=origin, destination=destination, day=day) for x in items]
    usable = [x for x in usable if x is not None]
    usable.sort(key=lambda x: Decimal(x["price_cny"]))
    return usable[0] if usable else None, usable

def validate_config(config: dict) -> list[tuple[str, str]]:
    if (config.get("origin") != "TFU" or config.get("destination") != "AAT"
            or config.get("direct_only") is not True or int(config.get("stay_nights", 0)) != 5):
        raise ValueError("Supplement requires existing TFU/AAT nonstop 5-night itinerary")
    days = config.get("departure_dates") or []
    if not 1 <= len(days) <= 7 or len(days) != len(set(days)):
        raise ValueError("Invalid monitored departure date count")
    pairs = []
    for dep in days:
        if not isinstance(dep, str) or not DATE_RE.fullmatch(dep):
            raise ValueError("Invalid date")
        ret = (date.fromisoformat(dep) + timedelta(days=5)).isoformat()
        pairs.append((dep, ret))
    return pairs

def get_public_items(browser, *, dep: str, arr: str, day: str):
    url = f"https://www.ly.com/flights/itinerary/oneway/{dep.lower()}-{arr.lower()}?date={day}"
    page = browser.new_page(locale="zh-CN")
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=22000)
        page.wait_for_timeout(2500)
        if (response is None or response.status != 200
                or urlparse(page.url).hostname != "www.ly.com"):
            return [], "page_unavailable"
        items = page.evaluate(JS)
        return (items, None) if isinstance(items, list) else ([], "data_shape_changed")
    except Exception as exc:
        return [], type(exc).__name__
    finally:
        page.close()

def run_snapshot(config: dict, prior: dict | None = None, *, getter=None, now=None):
    pairs = validate_config(config)
    old = (prior or {}).get("itineraries") or []
    old_by_day = {x.get("departure"): x for x in old if isinstance(x, dict)}
    now = now or datetime.now(BJT)
    records = []
    if getter is None:
        from playwright.sync_api import sync_playwright
        playwright = sync_playwright().start()
        binary = shutil.which("google-chrome") or shutil.which("chromium")
        opts = {"headless": True, "timeout": 25000}
        if binary:
            opts["executable_path"] = binary
        browser = playwright.chromium.launch(**opts)
        def getter(origin, dest, day):
            return get_public_items(browser, dep=origin, arr=dest, day=day)
    else:
        browser = playwright = None
    try:
        for dep, ret in pairs:
            stamp = datetime.now(BJT).isoformat(timespec="seconds")
            legs = []
            errors = []
            for origin, destination, day in (("TFU", "AAT", dep), ("AAT", "TFU", ret)):
                if date.fromisoformat(dep) < now.date():
                    items, err = [], "departure_in_past"
                else:
                    items, err = getter(origin, destination, day)
                    if browser is not None:
                        time.sleep(1.5)
                best, offers = cheapest(items, origin=origin, destination=destination, day=day)
                legs.append((best, offers))
                if err or not best:
                    errors.append(err or "no_valid_public_listing")
            out, back = legs
            both = out[0] is not None and back[0] is not None
            total = Decimal(out[0]["price_cny"]) + Decimal(back[0]["price_cny"]) if both else None
            previous = old_by_day.get(dep) or {}
            last_valid = ({"checked_at_bjt":stamp, "total_cny":str(total)}
                          if both else previous.get("last_valid"))
            records.append({
                "departure": dep, "return_date": ret,
                "checked_at_bjt": stamp,
                "status": "priced_reference" if both else "incomplete",
                "total_cny": str(total) if total is not None else None,
                "outbound": out[0], "return": back[0],
                "carrier_prices": {
                    "outbound": {x["carrier"]: x["price_cny"] for x in out[1]},
                    "return": {x["carrier"]: x["price_cny"] for x in back[1]},
                },
                "last_valid": last_valid,
                "error_types": errors[:2],
            })
    finally:
        if browser is not None:
            browser.close()
            playwright.stop()
    return {
        "schema_version": 1,
        "source": "tongcheng_public_listing",
        "generated_at_bjt": datetime.now(BJT).isoformat(timespec="seconds"),
        "cabin_verified": False,
        "taxes_verified": False,
        "baggage_verified": False,
        "bookability_verified": False,
        "itineraries": records,
    }

def main():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    prior = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    data = run_snapshot(config, prior)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    success = [x for x in data["itineraries"] if x["status"] == "priced_reference"]
    print("Tongcheng public listing: " + str(len(success)) + "/" +
          str(len(data["itineraries"])) + " complete pairs; unverified reference prices only.", flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("# 同程公开报价补充采集（不发送微信）\n\n")
            stream.write("| 行程 | 状态 | 往返未核实参考价 | 最低去/返航班 |\n|---|---|---:|---|\n")
            for row in data["itineraries"]:
                a = row.get("outbound") or {}
                b = row.get("return") or {}
                stream.write(f"| {row['departure']}→{row['return_date']} | {row['status']} | {row.get('total_cny') or '缺数据'} | {a.get('flight','—')} / {b.get('flight','—')} |\n")
            stream.write("\n数据只用于人工比较和备用监控观察，不进入自动低价微信决策。经济舱、税费、行李、库存均未核实。\n")

if __name__ == "__main__":
    main()
