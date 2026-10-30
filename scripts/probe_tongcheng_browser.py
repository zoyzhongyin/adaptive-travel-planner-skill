#!/usr/bin/env python3
"""Browser-only proof of public Tongcheng flight-data usability, no monitoring.

Only two read-only public booking pages. Uses a normal Chromium browser:
no stealth flags, CAPTCHA handling, cookie sharing, hidden endpoint calls,
automatic alerts, or personal credentials. Never logs raw HTML or JS.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout

BJT = timezone(timedelta(hours=8))
LEG_CASES = [
    ("2026-12-08", "TFU", "AAT"),
    ("2026-12-13", "AAT", "TFU"),
    ("2026-12-09", "TFU", "AAT"),
    ("2026-12-14", "AAT", "TFU"),
    ("2026-12-17", "TFU", "AAT"),
    ("2026-12-22", "AAT", "TFU"),
    ("2026-12-18", "TFU", "AAT"),
    ("2026-12-23", "AAT", "TFU"),
    ("2026-12-26", "TFU", "AAT"),
    ("2026-12-31", "AAT", "TFU"),
    ("2026-12-27", "TFU", "AAT"),
    ("2027-01-01", "AAT", "TFU"),
]
VALID_CARRIERS = {"CA", "3U", "9C"}
MAX_ITEMS = 12
JS = r"""() => {
  const state = window.__NUXT__ && window.__NUXT__.state
    && window.__NUXT__.state.book1;
  const list = state && Array.isArray(state.flightLists)
    ? state.flightLists : [];
  return {
    state_found: !!state,
    list_count: list.length,
    items: list.slice(0, 120).map(x => ({
      flight: String(x.flightNo || "").slice(0, 20),
      carrier: String(x.airCompanyCode || "").slice(0, 5),
      airline: String(x.airCompanyName || "").slice(0, 25),
      dep_airport: String(x.originAirportCode || "").slice(0, 8),
      arr_airport: String(x.arriveAirportCode || "").slice(0, 8),
      depart_date: String(x.flyOffTime || "").slice(0, 10),
      stop_num: x.stopNum,
      flight_price: x.flightPrice,
      product_price_count: x.productPrices &&
        typeof x.productPrices === "object" ?
        Object.keys(x.productPrices).length : 0
    }))
  };
}"""

def number(value):
    if type(value) not in (int, float):
        return None
    if not math.isfinite(value) or not (0 < value < 100000):
        return None
    return float(value)

def canonical(item, dep, arr, date):
    code = item.get("flight", "").upper()
    carrier = code[:2]
    if (carrier not in VALID_CARRIERS
        or not re.fullmatch(r"(?:CA|3U|9C)[0-9]{3,5}", code)
        or item.get("dep_airport") != dep
        or item.get("arr_airport") != arr
        or item.get("depart_date") != date
        or str(item.get("stop_num")) not in {"0", "0.0"}
    ):
        return None
    return {
        "flight": code, "carrier": carrier,
        "route": dep + "→" + arr, "date": date,
        "candidate_ticket_price": number(item.get("flight_price")),
        "price_verified": False,
    }

def probe():
    reports = []
    with sync_playwright() as p:
        binary = shutil.which("google-chrome") or shutil.which("chromium")
        args = {"headless": True, "timeout": 25000}
        if binary:
            args["executable_path"] = binary
        browser = p.chromium.launch(**args)
        try:
            for day, dep, arr in LEG_CASES:
                url = f"https://www.ly.com/flights/itinerary/oneway/{dep.lower()}-{arr.lower()}?date={day}"
                report = {"date": day, "route": dep + "→" + arr, "provider": "tongcheng"}
                page = browser.new_page(locale="zh-CN")
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(2500)
                    record = page.evaluate(JS)
                    matches = [canonical(x, dep, arr, day) for x in record["items"]]
                    valid = [x for x in matches if x is not None]
                    report.update({
                        "http": response.status if response else None,
                        "final_host": urlparse(page.url).hostname,
                        "state_present": record.get("state_found"),
                        "flightlist_count": record.get("list_count"),
                        "exact_airport_date_nonstop": len(valid),
                        "carrier_counts": {carrier: sum(x["carrier"] == carrier for x in valid)
                                           for carrier in sorted(VALID_CARRIERS)},
                        "sample": valid[:MAX_ITEMS],
                        "price_verified": False,
                    })
                except (BrowserTimeout, ValueError) as exc:
                    report["error_type"] = type(exc).__name__
                except Exception as exc:
                    report["error_type"] = type(exc).__name__
                finally:
                    page.close()
                print(json.dumps(report, ensure_ascii=False), flush=True)
                reports.append(report)
        finally:
            browser.close()
    return reports

def main():
    reports = probe()
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("# 同程只读浏览器验证 · TFU ⇄ AAT\n\n")
            f.write("Chromium 正常访问公开页面，不使用验证码绕过/反指纹/私人账户。无票价通知或写入生产状态。\n\n")
            f.write("| 日期航段 | HTTP | flightLists | 校验通过的直飞条目 | CA/3U/9C | \n|---|---|---|---|---|\n")
            for r in reports:
                counts = r.get("carrier_counts") or {}
                f.write(f"| {r['date']} {r['route']} | {r.get('http', r.get('error_type'))} | {r.get('flightlist_count')} | {r.get('exact_airport_date_nonstop')} | CA={counts.get('CA',0)},3U={counts.get('3U',0)},9C={counts.get('9C',0)} |\n")
            f.write("\n即使候选票价非空，也**不得**据此断定实际可售、经济舱、税费、雪具费用或原生航司价格；自动微信提醒仍禁用。\n")
            f.write("测试时间（北京时间）：" + datetime.now(BJT).isoformat(timespec="seconds") + "\n")

if __name__ == "__main__":
    main()
