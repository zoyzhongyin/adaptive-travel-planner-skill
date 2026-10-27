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
import time
from urllib import request
import urllib.error

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.flight_fare_query import query, OUT_DIR  # noqa: E402
from scripts.serverchan_push import send_wechat, DeliveryError  # noqa: E402

CONFIG_PATH = ROOT / "flight-watch/config.json"
STATE_PATH = ROOT / "flight-watch/state.json"
GH_REPO = os.environ.get("GITHUB_REPOSITORY", "")
GH_TOKEN = os.environ.pop("GITHUB_TOKEN", "")  # Do NOT pass repository credential to subprocesses (FlyAI CLI).
WECHAT_KEY = os.environ.pop("SERVERCHAN_SENDKEY", "")  # Do NOT pass SendKey to FlyAI subprocesses.


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


def snapshot_leg(offer):
    return {
        "flight": offer["legs"][0].get("flight"),
        "direct": bool(offer.get("direct")),
        "departure": offer.get("departure"),
        "price_cny_reference": offer["price_cny_reference"],
        "booking_url": offer.get("booking_url"),
    }


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


def pause(seconds):
    time.sleep(seconds)


def format_captured(iso_text):
    text = str(iso_text or "")
    if "T" in text:
        text = text[:16].replace("T", " ")
    return text + "（北京时间）"


def nonstop_label(offer):
    return "直飞" if offer.get("direct") else "非直飞"


def leg_diag(leg):
    attempts = leg.get("attempts") or []
    diag = {key: leg.get(key) for key in ("cli_exit", "api_status", "raw_offer_count", "error", "api_message", "platform_message")}
    diag["query_strategy"] = leg.get("query_strategy")
    diag["attempt_count"] = len(attempts)
    diag["attempt_statuses"] = [item.get("api_status") for item in attempts]
    diag["attempt_labels"] = [item.get("label") for item in attempts]
    return diag


def build_wechat_message(price, dep, ret, outward, inbound, captured_iso, *, ideal):
    """Reference-price alert. Taxes, baggage and ski fees stay unverified."""
    mark = "理想价" if ideal else "目标价"
    title = "阿勒泰机票" + mark + " ¥" + str(price)
    out_flight = str(outward["legs"][0].get("flight"))
    back_flight = str(inbound["legs"][0].get("flight"))
    out_url = outward.get("booking_url") or ""
    back_url = inbound.get("booking_url") or ""
    lines = [
        "**往返参考价合计：¥" + str(price) + " / 人**",
        "这是两张单程票的 ticketPrice 相加，不是已核实的往返结算价。",
        "出发：" + dep.isoformat() + "　返回：" + ret.isoformat(),
        "去程：" + nonstop_label(outward) + " " + out_flight + "，参考价 ¥" + str(outward["price_cny_reference"]),
        "返程：" + nonstop_label(inbound) + " " + back_flight + "，参考价 ¥" + str(inbound["price_cny_reference"]),
        "采集时间：" + format_captured(captured_iso),
        "税费、机建燃油：未核实",
        "托运行李：未核实",
        "雪具运输：未核实",
        "去程订票入口：" + (out_url or "接口未返回链接，请在飞猪按航班号搜索"),
        "返程订票入口：" + (back_url or "接口未返回链接，请在飞猪按航班号搜索"),
        "请打开订票页面确认含税总价、行李和雪具后再决定是否购买。监控不会自动购票。",
    ]
    if out_url:
        lines.append("[去程订票入口](" + out_url + ")")
    if back_url:
        lines.append("[返程订票入口](" + back_url + ")")
    return title, "\n\n".join(lines)


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


def maybe_heartbeat(state, now):
    """Keep a dated state heartbeat at most once in 21 days. Bot commits may not prevent GitHub schedule auto-disable, so alert the user about the 60-day risk."""
    seen = state.get("last_heartbeat_bjt")
    if seen:
        try:
            if now - datetime.fromisoformat(seen) < timedelta(days=21):
                return False
        except (TypeError, ValueError):
            pass
    state["last_heartbeat_bjt"] = now.isoformat(timespec="seconds")
    github_commit_state(state)
    return True


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
    now = datetime.now(timezone(timedelta(hours=8)))
    if index is None:
        remaining = [i for i, day in enumerate(dates) if date.fromisoformat(day) >= now.date()]
        if not remaining:
            remaining = list(range(len(dates)))
        index = remaining[int(datetime.now(timezone.utc).timestamp() // 1800) % len(remaining)]
    index = int(index) % len(dates)
    dep = date.fromisoformat(dates[index])
    ret = dep + timedelta(days=nights)
    pair_key = dep.isoformat() + "_" + ret.isoformat()
    result = {"query_time_bjt": now.isoformat(timespec="seconds"), "pair": pair_key, "index": index, "alert": False}

    if not config.get("enabled") or now.date() > date.fromisoformat(config["stop_after"]) or dep < now.date():
        result["status"] = "inactive_or_departed"
        write_summary("监控已到结束日期或被关闭，没有调用票价 API。", result)
        return False

    OUT_DIR.mkdir(exist_ok=True)
    direct_only = config.get("direct_only", True) is not False
    max_attempts = int(config.get("max_leg_attempts", 3))
    if live:
        outbound = query(
            config["origin"], config["destination"], dep, "watch_" + dep.isoformat() + "_out",
            direct_only=direct_only, max_attempts=max_attempts,
        )
        pause(1)
        inbound = query(
            config["destination"], config["origin"], ret, "watch_" + ret.isoformat() + "_back",
            direct_only=direct_only, max_attempts=max_attempts,
        )
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
    result["query_diagnostics"] = {
        name: leg_diag(leg) for name, leg in (("outbound", outbound), ("inbound", inbound))
    }
    result["taxes_verified"] = False
    result["baggage_verified"] = False
    result["ski_equipment_verified"] = False
    best = best_direct_price(outbound, inbound)
    if best is None:
        result["status"] = "incomplete_no_reliable_roundtrip_price"
        result["data_gap"] = True
        found = []
        outs, ins = only_direct(outbound), only_direct(inbound)
        if outs:
            result["outbound"] = snapshot_leg(outs[0])
            found.append("去程已取得直飞参考价 " + str(result["outbound"]["flight"]) + " ¥" + str(result["outbound"]["price_cny_reference"]))
        if ins:
            result["return"] = snapshot_leg(ins[0])
            found.append("返程已取得直飞参考价 " + str(result["return"]["flight"]) + " ¥" + str(result["return"]["price_cny_reference"]))
        held = "。".join(found) + "。" if found else "两段都没有可用的直飞参考价。"
        print("Query diagnostics: " + json.dumps(result["query_diagnostics"], ensure_ascii=False), flush=True)
        if live:
            maybe_heartbeat(state, now)
        write_summary(
            "检查日期：" + pair_key + "\n\n去程接口状态：" + str(result["outbound_status"])
            + "；返程接口状态：" + str(result["inbound_status"])
            + "。\n\n" + held
            + "\n\n**这是报价数据缺口：还没有两段可相加的直飞参考价，往返合计未计算。"
            + "不能据此判断没有航班，也不能据此判断价格高于预算。**",
            result,
        )
        return False

    price, outward, return_flight = best
    result["status"] = "priced_reference"
    result["data_gap"] = False
    result["reference_sum_cny"] = str(price)
    result["price_basis"] = "sum_of_two_one_way_ticketPrice_references"
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
    ideal = price <= Decimal(str(config["ideal_price_cny"]))
    result["alert"] = alert
    result["prior_alert_cny"] = prior
    delivery_channel = "none"
    if alert and live:
        # Attempt WeChat BEFORE marking as notified, so delivery failures
        # do not silently consume the alert. Fall back to GitHub email.
        delivery_channel = "github_email_fallback"
        if WECHAT_KEY:
            title, msg = build_wechat_message(
                price, dep, ret, outward, return_flight, result["query_time_bjt"], ideal=ideal,
            )
            try:
                send_wechat(WECHAT_KEY, title, msg)
                delivery_channel = "wechat"
            except DeliveryError as exc:
                result["wechat_error_code"] = str(exc)
            except Exception:
                result["wechat_error_code"] = "unexpected_push_failure"
        result["notification_channel"] = delivery_channel
        # Persist the best notified price only AFTER a successful WeChat
        # or a deliberate GitHub-email fallback signal.
        state.setdefault("alerts", {})[pair_key] = {
            "best_alert_cny": str(price),
            "last_alert_at_bjt": now.isoformat(timespec="seconds"),
            "delivery_channel": delivery_channel,
        }
        state["last_heartbeat_bjt"] = now.isoformat(timespec="seconds")
        github_commit_state(state)
    elif alert and not live:
        result["test_only_no_notification"] = True
        alert = False

    if live and not alert:
        maybe_heartbeat(state, now)

    lines = [
        "查询日期：" + pair_key,
        "采集时间：" + format_captured(result["query_time_bjt"]),
        "**两张直飞单程票参考报价合计：¥" + str(price) + "**",
        "去程：" + nonstop_label(outward) + " " + str(result["outbound"]["flight"])
        + "，参考价 ¥" + str(result["outbound"]["price_cny_reference"]),
        "返程：" + nonstop_label(return_flight) + " " + str(result["return"]["flight"])
        + "，参考价 ¥" + str(result["return"]["price_cny_reference"]),
        "税费、机建燃油、托运行李、雪具运输：未核实。ticketPrice 不是最终结算价。",
        "状态：" + ("命中理想目标，请尽快核实" if alert and ideal else "达到提醒阈值，请核实" if alert else "未产生新提醒（未达标或重复）"),
        "去程订票链接：" + str(outward.get("booking_url") or "接口未返回"),
        "返程订票链接：" + str(return_flight.get("booking_url") or "接口未返回"),
    ]
    write_summary("\n\n".join(lines), result, alert=(alert and delivery_channel != "wechat"))
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
