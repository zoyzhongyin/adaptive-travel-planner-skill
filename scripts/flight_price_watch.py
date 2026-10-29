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


def cheapest_direct_offer(leg):
    """Lowest direct ticketPrice. Airline is not a filter: 3U, CA, 9C and others compete."""
    directs = only_direct(leg)
    if not directs:
        return None
    return min(directs, key=lambda item: Decimal(str(item["price_cny_reference"])))


def best_direct_price(outbound, inbound):
    """Sum the cheapest direct on each separately queried leg. Never auto-purchase."""
    outward = cheapest_direct_offer(outbound)
    inbound_offer = cheapest_direct_offer(inbound)
    if outward is None or inbound_offer is None:
        return None
    price = Decimal(str(outward["price_cny_reference"])) + Decimal(str(inbound_offer["price_cny_reference"]))
    return (price, outward, inbound_offer)


def snapshot_leg(offer):
    first = (offer.get("legs") or [{}])[0]
    return {
        "flight": first.get("flight"),
        "airline": first.get("airline"),
        "direct": bool(offer.get("direct")),
        "departure": offer.get("departure"),
        "price_cny_reference": offer["price_cny_reference"],
        "booking_url": offer.get("booking_url"),
    }


def format_carrier(airline, flight) -> str:
    airline_text = str(airline or "").strip()
    flight_text = str(flight or "").strip()
    if airline_text and flight_text:
        return airline_text + " " + flight_text
    return flight_text or airline_text or "未知航班"


def leg_carrier(offer) -> str:
    first = ((offer or {}).get("legs") or [{}])[0]
    return format_carrier(first.get("airline"), first.get("flight"))


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


def build_wechat_message(price, dep, ret, outward, inbound, captured_iso, *, ideal, notes=None):
    """Reference-price alert. Taxes, baggage and ski fees stay unverified."""
    mark = "理想价" if ideal else "目标价"
    title = "阿勒泰机票" + mark + " ¥" + str(price)
    out_flight = leg_carrier(outward)
    back_flight = leg_carrier(inbound)
    out_url = outward.get("booking_url") or ""
    back_url = inbound.get("booking_url") or ""
    lines = [
        "**往返参考价合计：¥" + str(price) + " / 人**",
        "这是两张单程票的 ticketPrice 相加，不是已核实的往返结算价。",
        "出发：" + dep.isoformat() + "　返回：" + ret.isoformat(),
    ]
    if notes:
        lines.extend(notes)
    lines.extend([
        "去程：" + nonstop_label(outward) + " " + out_flight + "，参考价 ¥" + str(outward["price_cny_reference"]),
        "返程：" + nonstop_label(inbound) + " " + back_flight + "，参考价 ¥" + str(inbound["price_cny_reference"]),
        "采集时间：" + format_captured(captured_iso),
        "税费、机建燃油：未核实",
        "托运行李：未核实",
        "雪具运输：未核实",
        "去程订票入口：" + (out_url or "接口未返回链接，请在飞猪按航班号搜索"),
        "返程订票入口：" + (back_url or "接口未返回链接，请在飞猪按航班号搜索"),
        "请打开订票页面确认含税总价、行李和雪具后再决定是否购买。监控不会自动购票。",
    ])
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


PAIR_CAP = 7
ECONOMY_SEAT_CLASS = "经济舱"
DEFAULT_ROSTER = "日期按暂定排班推断（12月正式排班未出）"
DATE_STATE_BUCKETS = (
    "last_scan_bjt",
    "last_scan_results",
    "last_valid_quote_bjt",
    "consecutive_incomplete",
    "incomplete_since_bjt",
)


def validate_route(config) -> None:
    """Jiangjunshan via Altay AAT only. Connections, FYN and KJI stay out."""
    origin = str(config.get("origin") or "").upper()
    destination = str(config.get("destination") or "").upper()
    if origin != "TFU" or destination != "AAT":
        raise ValueError("route stays TFU-AAT only (Jiangjunshan via Altay); do not add FYN, KJI, or other airports")
    if config.get("direct_only", True) is False:
        raise ValueError("direct_only must stay true; connections are not monitored")
    for key in ("alternate_destinations", "connections", "transfer_airports"):
        if config.get(key):
            raise ValueError("connections and extra airports are not monitored")


def party_settings(config) -> dict:
    """1 adult, economy. FlyAI search-flight accepts cabin, not an adults count."""
    if "adults" in config and type(config["adults"]) is not int:
        raise ValueError("adults must be an integer")
    adults = int(config.get("adults", 1))
    cabin = str(config.get("cabin", "economy")).strip().lower()
    if adults != 1:
        raise ValueError("adults must be 1")
    if cabin != "economy":
        raise ValueError("cabin must be economy")
    return {
        "adults": 1,
        "cabin": "economy",
        "seat_class_name": ECONOMY_SEAT_CLASS,
        "adults_cli_supported": False,
        "cabin_cli_flag": "--seat-class-name",
    }


def annotation_lines(config, dep, ret) -> list[str]:
    lines = [str(config.get("roster_notice") or DEFAULT_ROSTER)]
    lines.append("乘客：1 成人，经济舱。")
    for item in config.get("calendar_conflicts") or []:
        if not isinstance(item, dict) or "date" not in item:
            continue
        day = date.fromisoformat(str(item["date"]))
        if dep <= day <= ret:
            title = str(item.get("title") or "")
            lines.append("日历冲突：" + day.isoformat() + " 全天「" + title + "」与本次行程重叠。")
    return lines


def _windows(config) -> list[dict]:
    windows = []
    for raw in config.get("rest_windows") or []:
        if not isinstance(raw, dict):
            raise ValueError("rest_windows entries must be objects")
        window = dict(raw)
        for key in ("anchor", "start", "end"):
            if key not in window:
                raise ValueError("rest_windows entries need anchor, start, and end")
            date.fromisoformat(str(window[key]))
        if str(window["start"]) > str(window["end"]):
            raise ValueError("rest window start is after end")
        window["id"] = str(window.get("id") or window["anchor"])
        window["anchor"] = str(window["anchor"])
        window["start"] = str(window["start"])
        window["end"] = str(window["end"])
        windows.append(window)
    return windows


def expand_departure_dates(config) -> list[str]:
    """Anchors plus in-window ±flex departures, capped at 7.

    A flex date is kept only when the departure itself falls inside that
    anchor's rest window. Pre-window days are dropped before out-of-window
    neighbors can crowd out an anchor. stay_nights stays global, so a +1
    departure returns one day after the anchor's rest-window end.
    """
    anchors = config.get("departure_anchors")
    if not isinstance(anchors, list) or not anchors:
        raise ValueError("departure_anchors must be a non-empty list")
    flex = int(config.get("date_flex_days") or 0)
    if flex < 0 or flex > 3:
        raise ValueError("date_flex_days must be 0..3")
    nights = int(config["stay_nights"])
    if not 1 <= nights <= 14:
        raise ValueError("stay_nights out of bounds")
    parsed_anchors = []
    for anchor in anchors:
        iso = date.fromisoformat(str(anchor)).isoformat()
        if iso not in parsed_anchors:
            parsed_anchors.append(iso)
    if len(parsed_anchors) > PAIR_CAP:
        raise ValueError("too many anchors for the 7-pair cap")
    windows = {item["anchor"]: item for item in _windows(config)}
    chosen = list(parsed_anchors)
    pool = []
    for anchor in parsed_anchors:
        window = windows.get(anchor)
        if window is None or flex == 0:
            continue
        anchor_day = date.fromisoformat(anchor)
        start = date.fromisoformat(window["start"])
        end = date.fromisoformat(window["end"])
        for delta in range(-flex, flex + 1):
            if delta == 0:
                continue
            dep = anchor_day + timedelta(days=delta)
            if not (start <= dep <= end):
                continue
            ret = dep + timedelta(days=nights)
            return_inside = start <= ret <= end
            pool.append(((0 if return_inside else 1, abs(delta), dep.isoformat()), dep.isoformat()))
    pool.sort()
    seen = set(chosen)
    for _rank, dep in pool:
        if dep in seen:
            continue
        if len(chosen) >= PAIR_CAP:
            break
        chosen.append(dep)
        seen.add(dep)
    return sorted(chosen)


def monitored_departure_dates(config) -> list[str]:
    if config.get("departure_anchors"):
        resolved = expand_departure_dates(config)
        explicit = config.get("departure_dates")
        if explicit is not None and [str(day) for day in explicit] != resolved:
            raise ValueError("departure_dates must match the expanded anchors: " + ", ".join(resolved))
        dates = resolved
    else:
        dates = [str(day) for day in (config.get("departure_dates") or [])]
    if not 1 <= len(dates) <= PAIR_CAP:
        raise ValueError("departure_dates must have 1–7 dates")
    return dates


def prune_retired_itineraries(state: dict, active_dates: list[str]) -> list[str]:
    """Drop scan/alert keys for departures that are no longer monitored."""
    active = set(active_dates)
    removed = []
    for bucket in DATE_STATE_BUCKETS:
        data = state.get(bucket)
        if not isinstance(data, dict):
            continue
        for key in list(data):
            if key not in active:
                data.pop(key, None)
                removed.append(bucket + ":" + key)
    alerts = state.get("alerts")
    if isinstance(alerts, dict):
        for key in list(alerts):
            departure = str(key).split("_", 1)[0]
            if departure not in active:
                alerts.pop(key, None)
                removed.append("alerts:" + key)
    window_alerts = state.get("window_alerts")
    if isinstance(window_alerts, dict):
        for key, val in list(window_alerts.items()):
            departure = val.get("departure") if isinstance(val, dict) else None
            if departure and departure not in active:
                window_alerts.pop(key, None)
                removed.append("window_alerts:" + key)
    return removed


def dates_in_window(config, window) -> list[str]:
    start, end = window["start"], window["end"]
    return [dep for dep in monitored_departure_dates(config) if start <= dep <= end]


def lowest_in_window(config, state, window):
    best = None
    results = state.get("last_scan_results") or {}
    for dep in dates_in_window(config, window):
        record = results.get(dep) or {}
        if record.get("status") != "priced_reference" or not record.get("reference_total_cny"):
            continue
        price = Decimal(str(record["reference_total_cny"]))
        if best is None or price < best["price"] or (price == best["price"] and dep < best["departure"]):
            best = {"price": price, "departure": dep, "record": record, "window": window}
    return best


def window_prior(state, window, departures):
    saved = (state.get("window_alerts") or {}).get(window["id"])
    if isinstance(saved, dict) and saved.get("best_alert_cny"):
        return saved.get("best_alert_cny")
    prior = None
    alerts = state.get("alerts") or {}
    if not isinstance(alerts, dict):
        return None
    for dep in departures:
        prefix = dep + "_"
        for key, val in alerts.items():
            if key.startswith(prefix) and isinstance(val, dict) and val.get("best_alert_cny"):
                price = Decimal(str(val["best_alert_cny"]))
                if prior is None or price < prior:
                    prior = price
    return None if prior is None else str(prior)


def record_return(config, dep: str, record: dict) -> date:
    text = record.get("return_date")
    if text:
        return date.fromisoformat(str(text))
    return date.fromisoformat(dep) + timedelta(days=int(config["stay_nights"]))


def format_window_digest(config, state) -> str:
    if not config.get("rest_windows"):
        return ""
    lines = [
        "## 各窗口最低直飞组合",
        "每窗口只列一条最低往返（航司、日期、链接）。邻近日期不单独再报一条。",
        str(config.get("roster_notice") or DEFAULT_ROSTER),
        "乘客：1 成人，经济舱。两段分开查询后相加；每段取最低直飞，不限航司。不自动购票。",
    ]
    for window in _windows(config):
        best = lowest_in_window(config, state, window)
        label = window["start"] + "–" + window["end"] + "（锚点 " + window["anchor"] + "）"
        if best is None:
            lines.append("- " + label + "：尚无完整直飞往返参考价")
            continue
        record = best["record"]
        dep = date.fromisoformat(best["departure"])
        ret = record_return(config, best["departure"], record)
        out_name = format_carrier(record.get("outbound_airline"), record.get("outbound_flight"))
        back_name = format_carrier(record.get("return_airline"), record.get("return_flight"))
        lines.append(
            "- " + label + "：最低 " + dep.isoformat() + " → " + ret.isoformat()
            + "，去程 " + out_name + " ¥" + str(record.get("outbound_price_cny"))
            + "，返程 " + back_name + " ¥" + str(record.get("return_price_cny"))
            + "，合计 ¥" + str(best["price"])
        )
        lines.append("  去程链接：" + (record.get("outbound_url") or "接口未返回"))
        lines.append("  返程链接：" + (record.get("return_url") or "接口未返回"))
        for note in annotation_lines(config, dep, ret):
            if note.startswith("日历冲突"):
                lines.append("  " + note)
    return "\n".join(lines)


def _snapshot_offer(record, side: str) -> dict:
    prefix = "outbound" if side == "outbound" else "return"
    return {
        "direct": True,
        "price_cny_reference": record.get(prefix + "_price_cny"),
        "booking_url": record.get(prefix + "_url") or "",
        "legs": [{
            "flight": record.get(prefix + "_flight"),
            "airline": record.get(prefix + "_airline"),
        }],
    }


def notify_window_winners(config, state, scanned_departures, now) -> bool:
    """Send at most one WeChat/email alert per rest window: the lowest combo."""
    if not config.get("rest_windows"):
        return False
    scanned = set(scanned_departures)
    fallback = False
    for window in _windows(config):
        best = lowest_in_window(config, state, window)
        if best is None or best["departure"] not in scanned:
            continue
        members = dates_in_window(config, window)
        prior = window_prior(state, window, members)
        if not should_alert(best["price"], prior, config):
            continue
        record = best["record"]
        dep = date.fromisoformat(best["departure"])
        ret = record_return(config, best["departure"], record)
        ideal = best["price"] <= Decimal(str(config["ideal_price_cny"]))
        notes = annotation_lines(config, dep, ret)
        channel = "github_email_fallback"
        captured = record.get("checked_at_bjt") or now.isoformat(timespec="seconds")
        if WECHAT_KEY:
            title, msg = build_wechat_message(
                best["price"], dep, ret,
                _snapshot_offer(record, "outbound"),
                _snapshot_offer(record, "return"),
                captured, ideal=ideal, notes=notes,
            )
            try:
                send_wechat(WECHAT_KEY, title, msg)
                channel = "wechat"
            except DeliveryError:
                channel = "github_email_fallback"
            except Exception:
                channel = "github_email_fallback"
        if channel != "wechat":
            fallback = True
        payload = {
            "best_alert_cny": str(best["price"]),
            "last_alert_at_bjt": now.isoformat(timespec="seconds"),
            "delivery_channel": channel,
            "departure": dep.isoformat(),
            "return": ret.isoformat(),
        }
        state.setdefault("alerts", {})[dep.isoformat() + "_" + ret.isoformat()] = payload
        state.setdefault("window_alerts", {})[window["id"]] = payload
    return fallback


def effective_leg_attempts(config, state, dep_day: str) -> int:
    """Avoid hammering FlyAI after repeated generic status=1 / empty quote gaps.

    A normal query gets all configured official shapes. After three consecutive
    incomplete round-trip scans, try the base shape once per leg, restoring
    the full query plan every sixth incomplete scan for recovery detection.
    Any successful complete quote resets the failure count in the batch runner.
    No bypass of provider rate controls; fewer calls on persistent failure.
    """
    configured = int(config.get("max_leg_attempts", 3))
    if not 1 <= configured <= 3:
        raise ValueError("max_leg_attempts must be 1–3")
    streak = int((state.get("consecutive_incomplete") or {}).get(dep_day) or 0)
    if streak >= 3 and streak % 6 != 0:
        return 1
    return configured


def perform(config, state, *, index=None, live=True, notify=True):
    validate_route(config)
    party = party_settings(config)
    dates = monitored_departure_dates(config)
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
    result = {
        "query_time_bjt": now.isoformat(timespec="seconds"),
        "pair": pair_key,
        "index": index,
        "alert": False,
        "return_date": ret.isoformat(),
        "party": party,
        "annotations": annotation_lines(config, dep, ret),
    }

    if not config.get("enabled") or now.date() > date.fromisoformat(config["stop_after"]) or dep < now.date():
        result["status"] = "inactive_or_departed"
        write_summary("监控已到结束日期或被关闭，没有调用票价 API。", result)
        return False

    OUT_DIR.mkdir(exist_ok=True)
    direct_only = config.get("direct_only", True) is not False
    max_attempts = effective_leg_attempts(config, state, dep.isoformat())
    if live and max_attempts < int(config.get("max_leg_attempts", 3)):
        print("Repeated incomplete quote: using one attempt per leg to reduce API pressure; periodic full retries remain enabled.", flush=True)
    if live:
        print(
            "Party: 1 adult, economy. Sending --seat-class-name " + party["seat_class_name"]
            + ". FlyAI search-flight has no adults parameter; adults=1 is not sent.",
            flush=True,
        )
        outbound = query(
            config["origin"], config["destination"], dep, "watch_" + dep.isoformat() + "_out",
            direct_only=direct_only, max_attempts=max_attempts,
            seat_class_name=party["seat_class_name"],
        )
        pause(1)
        inbound = query(
            config["destination"], config["origin"], ret, "watch_" + ret.isoformat() + "_back",
            direct_only=direct_only, max_attempts=max_attempts,
            seat_class_name=party["seat_class_name"],
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
        out_best = cheapest_direct_offer(outbound)
        in_best = cheapest_direct_offer(inbound)
        if out_best:
            result["outbound"] = snapshot_leg(out_best)
            found.append("去程已取得直飞参考价 " + format_carrier(result["outbound"].get("airline"), result["outbound"].get("flight")) + " ¥" + str(result["outbound"]["price_cny_reference"]))
        if in_best:
            result["return"] = snapshot_leg(in_best)
            found.append("返程已取得直飞参考价 " + format_carrier(result["return"].get("airline"), result["return"].get("flight")) + " ¥" + str(result["return"]["price_cny_reference"]))
        held = "。".join(found) + "。" if found else "两段都没有可用的直飞参考价。"
        print("Query diagnostics: " + json.dumps(result["query_diagnostics"], ensure_ascii=False), flush=True)
        if live:
            maybe_heartbeat(state, now)
        write_summary(
            "检查日期：" + pair_key + "\n\n去程接口状态：" + str(result["outbound_status"])
            + "；返程接口状态：" + str(result["inbound_status"])
            + "。\n\n" + held
            + "\n\n**这是报价数据缺口：还没有两段可相加的直飞参考价，往返合计未计算。"
            + "不能据此判断没有航班，也不能据此判断价格高于预算。**"
            + "\n\n" + "\n\n".join(result["annotations"]),
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
        "airline": outward["legs"][0].get("airline"),
        "departure": outward.get("departure"),
        "price_cny_reference": outward["price_cny_reference"],
        "booking_url": outward.get("booking_url"),
    }
    result["return"] = {
        "flight": return_flight["legs"][0].get("flight"),
        "airline": return_flight["legs"][0].get("airline"),
        "departure": return_flight.get("departure"),
        "price_cny_reference": return_flight["price_cny_reference"],
        "booking_url": return_flight.get("booking_url"),
    }

    seen = state.get("alerts", {}).get(pair_key)
    prior = seen.get("best_alert_cny") if isinstance(seen, dict) else None
    wants_alert = should_alert(price, prior, config)
    ideal = price <= Decimal(str(config["ideal_price_cny"]))
    result["prior_alert_cny"] = prior
    delivery_channel = "none"
    alert = False
    if not notify:
        # The batch runner sends one message per rest window after every due pair is priced.
        result["pair_would_alert"] = wants_alert
        result["alert"] = False
        result["notification_channel"] = "deferred_to_window"
    elif wants_alert and live:
        alert = True
        result["alert"] = True
        # Attempt WeChat BEFORE marking as notified, so delivery failures
        # do not silently consume the alert. Fall back to GitHub email.
        delivery_channel = "github_email_fallback"
        if WECHAT_KEY:
            title, msg = build_wechat_message(
                price, dep, ret, outward, return_flight, result["query_time_bjt"],
                ideal=ideal, notes=result["annotations"],
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
    elif wants_alert and not live:
        result["test_only_no_notification"] = True
        result["alert"] = False
    else:
        result["alert"] = False

    if live and notify and not alert:
        maybe_heartbeat(state, now)

    if not notify:
        status_line = "状态：报价已记录。用户提醒按休息窗口汇总，每窗口只发一条最低组合。"
    elif alert and ideal:
        status_line = "状态：命中理想目标，请尽快核实"
    elif alert:
        status_line = "状态：达到提醒阈值，请核实"
    else:
        status_line = "状态：未产生新提醒（未达标或重复）"
    lines = [
        "查询日期：" + pair_key,
        "采集时间：" + format_captured(result["query_time_bjt"]),
        "**两张直飞单程票参考报价合计：¥" + str(price) + "**",
        "去程：" + nonstop_label(outward) + " " + format_carrier(result["outbound"].get("airline"), result["outbound"].get("flight"))
        + "，参考价 ¥" + str(result["outbound"]["price_cny_reference"]),
        "返程：" + nonstop_label(return_flight) + " " + format_carrier(result["return"].get("airline"), result["return"].get("flight"))
        + "，参考价 ¥" + str(result["return"]["price_cny_reference"]),
    ]
    lines.extend(result["annotations"])
    lines.extend([
        "税费、机建燃油、托运行李、雪具运输：未核实。ticketPrice 不是最终结算价。",
        status_line,
        "去程订票链接：" + str(outward.get("booking_url") or "接口未返回"),
        "返程订票链接：" + str(return_flight.get("booking_url") or "接口未返回"),
    ])
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
