#!/usr/bin/env python3
"""Near-real-time FlightAI price watch for GitHub Actions.

One date pair per scheduled run; real flight data is obtained from FlyAI.
Alerts are conditionally signalled through an Actions failure notification,
NOT by ChatGPT. No booking, login, private info, or rate-limit bypass.
"""
from __future__ import annotations

import base64
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from urllib import request
import urllib.error

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.flight_fare_query import query, OUT_DIR  # noqa: E402

CONFIG_PATH = ROOT / "flight-watch/config.json"
STATE_PATH = ROOT / "flight-watch/state.json"
GH_REPO = os.environ.get("GITHUB_REPOSITORY", "")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")


def json_read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def only_direct(leg):
    return [x for x in leg.get("offers", []) if x.get("direct") and x.get("price_cny_reference") is not None]


def best_direct_price(outbound, inbound):
    outs, ins = only_direct(outbound), only_direct(inbound)
    if not outs or not ins:
        return None
    a, b = outs[0], ins[0]
    return (Decimal(a["price_cny_reference"]) + Decimal(b["price_cny_reference"]), a, b)


def should_alert(price, previous, config):
    limit = Decimal(str(config["alert_price_cny"]))
    ideal = Decimal(str(config["ideal_price_cny"]))
    drop = Decimal(str(config["min_drop_cny"]))
    if price > limit:
        return False
    if previous is None:
        return True
    previous = Decimal(str(previous))
    return (price <= previous - drop) or (price <= ideal < previous)


def github_commit_state(state):
    """Write only alert state / rare heartbeat to GitHub repository, never secrets."""
    if not (GH_REPO and GH_TOKEN):
        raise RuntimeError("GitHub token missing: alert state cannot persist safely")
    api_url = "https://api.github.com/repos/" + GH_REPO + "/contents/flight-watch/state.json"
    headers = {
        "Authorization": "Bearer " + GH_TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "AltayFlightWatcher/1.0",
    }
    with request.urlopen(request.Request(api_url, headers=headers), timeout=15) as r:
        current = json.load(r)
    content = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    payload = json.dumps({
        "message": "Flight-watch: persist deduplicated alert state",
        "content": base64.b64encode(content).decode("ascii"),
        "sha": current["sha"],
    }).encode("utf-8")
    call = request.Request(api_url, headers=headers, data=payload, method="PUT")
    with request.urlopen(call, timeout=20) as r:
        _ = json.load(r)


def write_summary(message, result, alert=False):
    OUT_DIR.mkdir(exist_ok=True)
    out = "# 阿勒泰机票价格监控\n\n" + message + "\n"
    (OUT_DIR / "watch-result.md").write_text(out, encoding="utf-8")
    (OUT_DIR / "watch-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(out)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write("price_alert=" + ("true" if alert else "false") + "\n")


def perform(config, state, *, index=None, live=True):
    dates = config.get("departure_dates")
    if not isinstance(dates, list) or not 1 <= len(dates) <= 7:
        raise ValueError("departure_dates must have 1–7 dates")
    nights = int(config["stay_nights"])
    if not 1 <= nights <= 14:
        raise ValueError("stay_nights out of bounds")
    if index is None:
        index = int(datetime.now(timezone.utc).timestamp() // 1800) % len(dates)
    index = int(index) % len(dates)
    dep = date.fromisoformat(dates[index])
    ret = dep + timedelta(days=nights)
    pair_key = dep.isoformat() + "_" + ret.isoformat()
    now = datetime.now(timezone(timedelta(hours=8)))
    result = {"query_time_bjt": now.isoformat(timespec="seconds"), "pair": pair_key, "index": index, "alert": False}

    if not config.get("enabled") or now.date() > date.fromisoformat(config["stop_after"]) or dep < now.date():
        result["status"] = "inactive_or_departed"
        write_summary("监控已到结束日期或被关闭，没有调用票价 API。", result)
        return False

    OUT_DIR.mkdir(exist_ok=True)
    if live:
        outbound = query(config["origin"], config["destination"], dep, "watch_" + dep.isoformat() + "_out")
        inbound = query(config["destination"], config["origin"], ret, "watch_" + ret.isoformat() + "_back")
    else:
        # Fixture for a deterministic installation test; never considered market data.
        def mock_one(o, d, day, amount, no):
            return {"api_status": 0, "offers": [{
                "direct": True, "price_cny_reference": str(amount),
                "departure": str(day) + " 10:00:00",
                "arrival": str(day) + " 14:00:00",
                "booking_url": None,
                "legs": [{"flight": no, "from": o, "to": d}],
            }]}
        outbound = mock_one(config["origin"], config["destination"], dep, 600, "TEST001")
        inbound = mock_one(config["destination"], config["origin"], ret, 620, "TEST002")

    result["outbound_status"] = outbound.get("api_status")
    result["inbound_status"] = inbound.get("api_status")
    best = best_direct_price(outbound, inbound)
    if best is None:
        result["status"] = "incomplete_no_reliable_roundtrip_price"
        write_summary(
            "检查日期：" + pair_key + "\n\n去程接口状态：" + str(result["outbound_status"])
            + "；返程接口状态：" + str(result["inbound_status"])
            + "。**尚无可比较的两段直飞价格，不代表没有航班。**",
            result,
        )
        return False

    price, outward, return_flight = best
    result["status"] = "priced_reference"
    result["reference_sum_cny"] = str(price)
    result["outbound"] = {
        "flight": outward["legs"][0].get("flight"),
        "departure": outward.get("departure"),
        "price_cny_reference": outward["price_cny_reference"],
        "booking_url": outward.get("booking_url"),
    }
    result["return"] = {
        "flight": return_flight["legs"][0].get("flight"),
        "departure": return_flight.get("departure"),
        "price_cny_reference": return_flight["price_cny_reference"],
        "booking_url": return_flight.get("booking_url"),
    }

    seen = state.get("alerts", {}).get(pair_key)
    prior = seen.get("best_alert_cny") if isinstance(seen, dict) else None
    alert = should_alert(price, prior, config)
    result["alert"] = alert
    result["prior_alert_cny"] = prior
    if alert and live:
        # Commit first, so a retry does not generate duplicate alerts.
        state.setdefault("alerts", {})[pair_key] = {
            "best_alert_cny": str(price), "last_alert_at_bjt": now.isoformat(timespec="seconds"),
        }
        github_commit_state(state)
    elif alert and not live:
        result["test_only_no_notification"] = True
        alert = False

    ideal = price <= Decimal(str(config["ideal_price_cny"]))
    lines = [
        "查询日期：" + pair_key,
        "**两张直飞单程票参考报价合计：¥" + str(price) + "**",
        "去程：" + str(result["outbound"]["flight"]) + "，¥" + str(result["outbound"]["price_cny_reference"]) + "；返程："
        + str(result["return"]["flight"]) + "，¥" + str(result["return"]["price_cny_reference"]),
        "**重要：飞猪 API 的 ticketPrice 不能当作已含税、行李和雪具的最终结算价。**",
        "状态：" + ("命中理想目标，请尽快核实" if alert and ideal else "达到提醒阈值，请核实" if alert else "未产生新提醒（未达标或重复）"),
        "去程订票链接：" + str(outward.get("booking_url")),
        "返程订票链接：" + str(return_flight.get("booking_url")),
    ]
    write_summary("\n\n".join(lines), result, alert=alert)
    return alert


if __name__ == "__main__":
    config = json_read(CONFIG_PATH)
    state = json_read(STATE_PATH)
    test = "--test" in sys.argv
    watch_index = 0 if test else None
    try:
        alarm = perform(config, state, index=watch_index, live=not test)
    except Exception as exc:
        print("Flight monitor encountered an error: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        raise
