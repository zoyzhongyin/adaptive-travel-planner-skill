#!/usr/bin/env python3
"""Adaptive flight-price batch runner.

GitHub schedule may be delayed or dropped. Prioritize unscanned and stale
date pairs; inspect all overdue pairs on the next actual run, and record
coverage persistently so timing jitter cannot starve the same itinerary.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import flight_price_watch as watch
from scripts.serverchan_push import DeliveryError

BJT = timezone(timedelta(hours=8))
ANOMALY_AFTER = timedelta(hours=8)
# Free ServerChan quota is precious: one anomaly notice per outage episode,
# and no more than one anomaly notice on a Beijing calendar day.
ANOMALY_COOLDOWN = timedelta(hours=24)


def validated_schedule(config: dict) -> tuple[int, int, int]:
    success = int(config.get("each_pair_interval_minutes", 60))
    base = int(config.get("failure_retry_minutes", 20))
    cap = int(config.get("max_pairs_per_run", 3))
    if not (15 <= success <= 1440 and 1 <= cap <= 7 and 10 <= base <= success):
        raise ValueError("Invalid per-pair scan interval or batch-size")
    return success, base, cap


def pair_interval_minutes(config: dict, state: dict, dep: str) -> int:
    """Successful quotes wait out the normal interval. Data gaps retry sooner, then back off."""
    success, base, _ = validated_schedule(config)
    rec = (state.get("last_scan_results") or {}).get(dep) or {}
    if rec.get("status") != "incomplete_no_reliable_roundtrip_price":
        return success
    streak = int((state.get("consecutive_incomplete") or {}).get(dep) or 1)
    if streak < 1:
        streak = 1
    wait = base * (2 ** min(streak - 1, 3))
    return min(success, wait)


def select_due_dates(config: dict, state: dict, now: datetime) -> list[tuple[int, str]]:
    dates = watch.monitored_departure_dates(config)
    last = state.get("last_scan_bjt", {})
    _, _, cap = validated_schedule(config)
    due = []
    for i, dep in enumerate(dates):
        if date.fromisoformat(dep) < now.date():
            continue
        prior = last.get(dep)
        if prior:
            try:
                last_time = datetime.fromisoformat(prior)
                if last_time.tzinfo is None:
                    raise ValueError("Missing time zone")
                last_time = last_time.astimezone(BJT)
            except (TypeError, ValueError):
                last_time = None
        else:
            last_time = None
        gap = pair_interval_minutes(config, state, dep)
        if last_time is None or (now - last_time) >= timedelta(minutes=gap):
            due.append((last_time or datetime(2000, 1, 1, tzinfo=BJT), i, dep))
    due.sort(key=lambda item: (item[0], item[2]))
    return [(i, dep) for _, i, dep in due[:cap]]


def note_quote_health(state: dict, dep: str, status: str, checked_at: str) -> None:
    if status == "priced_reference":
        state.setdefault("last_valid_quote_bjt", {})[dep] = checked_at
        state.setdefault("consecutive_incomplete", {})[dep] = 0
        state.setdefault("incomplete_since_bjt", {}).pop(dep, None)
    elif status == "incomplete_no_reliable_roundtrip_price":
        streaks = state.setdefault("consecutive_incomplete", {})
        streaks[dep] = int(streaks.get(dep) or 0) + 1
        state.setdefault("incomplete_since_bjt", {}).setdefault(dep, checked_at)


def monitor_gaps(state: dict, departure_dates: list, now: datetime, *,
                 after: timedelta = ANOMALY_AFTER) -> list:
    """Dates with no valid round-trip reference for `after`. Empty when none, or when cooling down."""
    gaps = []
    valid = state.get("last_valid_quote_bjt") or {}
    since_map = state.get("incomplete_since_bjt") or {}
    for dep in departure_dates:
        since = since_map.get(dep)
        if not since:
            continue
        try:
            started = datetime.fromisoformat(since)
            if started.tzinfo is None:
                started = started.replace(tzinfo=BJT)
        except (TypeError, ValueError):
            continue
        last_ok = valid.get(dep)
        if last_ok:
            try:
                ok_at = datetime.fromisoformat(last_ok)
                if ok_at.tzinfo is None:
                    ok_at = ok_at.replace(tzinfo=BJT)
                if ok_at >= started:
                    continue
            except (TypeError, ValueError):
                pass
        if now - started >= after:
            gaps.append(dep)
    return gaps


def anomaly_on_cooldown(state: dict, now: datetime, *, cooldown: timedelta = ANOMALY_COOLDOWN) -> bool:
    last_alert = state.get("last_anomaly_alert_bjt")
    if not last_alert:
        return False
    try:
        sent = datetime.fromisoformat(last_alert)
        if sent.tzinfo is None:
            sent = sent.replace(tzinfo=BJT)
    except (TypeError, ValueError):
        return False
    return now - sent < cooldown


def anomaly_episode_active(state: dict) -> bool:
    """Treat old persisted alert state as an ongoing incident after an upgrade.

    Only a *fully recovered* monitor resets the incident. New affected dates
    appearing during the same outage do not produce more paid/quota-limited
    messages. Price alerts are independent of this flag.
    """
    if "anomaly_episode_active" in state:
        return bool(state["anomaly_episode_active"])
    return bool(state.get("last_anomaly_alert_bjt") and state.get("last_anomaly_gaps"))


def should_notify_anomaly(state: dict, gaps: list[str], now: datetime) -> bool:
    if not gaps or anomaly_episode_active(state):
        return False
    # If a monitor recovers and fails again on the same calendar day, avoid
    # using a second free ServerChan slot even though the incident is new.
    last = state.get("last_anomaly_alert_bjt")
    if last:
        try:
            prior = datetime.fromisoformat(last)
            if prior.tzinfo is None:
                prior = prior.replace(tzinfo=BJT)
            if prior.astimezone(BJT).date() == now.astimezone(BJT).date():
                return False
        except (ValueError, TypeError):
            pass
    return not anomaly_on_cooldown(state, now)


def human_bjt(value) -> str:
    if not value:
        return "尚无"
    try:
        day = datetime.fromisoformat(str(value))
        if day.tzinfo is None:
            day = day.replace(tzinfo=BJT)
        return day.astimezone(BJT).strftime("%m月%d日 %H:%M")
    except (ValueError, TypeError):
        return "时间不详"


def build_anomaly_message(gaps: list, state: dict) -> tuple[str, str]:
    title = "阿勒泰机票监控异常：缺有效报价"
    valid = state.get("last_valid_quote_bjt") or {}
    since_map = state.get("incomplete_since_bjt") or {}
    lines = [
        "当前 " + str(len(gaps)) + " 组出发日期持续未取得完整往返参考价。",
        "这是数据源异常，不代表没有航班或票价超过预算。",
        "本轮持续故障只提醒一次；价格达标提醒仍会独立发送。",
    ]
    for dep in gaps:
        lines.append(
            dep[5:].replace("-", "月") + "日：异常始于"
            + human_bjt(since_map.get(dep))
            + "；上次完整报价 " + human_bjt(valid.get(dep))
        )
    lines.append("可打开阿勒泰机票看板查看当前状态，无需手动干预。")
    return title, "\n\n".join(lines)


def notify_anomaly(state: dict, gaps: list, now: datetime) -> bool:
    """Send one rate-limited anomaly notice. Return True when GitHub email should be the backup."""
    title, body = build_anomaly_message(gaps, state)
    channel = "github_email_fallback"
    if watch.WECHAT_KEY:
        try:
            watch.send_wechat(watch.WECHAT_KEY, title, body)
            channel = "wechat"
        except DeliveryError:
            channel = "github_email_fallback"
        except Exception:
            channel = "github_email_fallback"
    state["last_anomaly_alert_bjt"] = now.isoformat(timespec="seconds")
    state["last_anomaly_channel"] = channel
    state["last_anomaly_gaps"] = list(gaps)
    return channel != "wechat"


def report_output(price_alert, anomaly_alert=False, due=None):
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as stream:
            stream.write("price_alert=" + ("true" if price_alert else "false") + "\n")
            stream.write("anomaly_alert=" + ("true" if anomaly_alert else "false") + "\n")
            if due is not None:
                stream.write("due=" + ("true" if due else "false") + "\n")


def select_only(config, state, now):
    if not config.get("enabled") or now.date() > date.fromisoformat(config["stop_after"]):
        due = []
    else:
        due = select_due_dates(config, {} if os.environ.get("FORCE_SCAN") == "true" else state, now)
    dates = [dep for _, dep in due]
    message = ("Due itineraries: " + ", ".join(dates)) if dates else "No itinerary due; skipped FlyAI. Workflow start is not a valid fare."
    print(message)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    report_output(False, False, due=bool(dates))


def main():
    config = watch.json_read(watch.CONFIG_PATH)
    state = watch.json_read(watch.STATE_PATH)
    now = datetime.now(BJT)
    if "--select-only" in sys.argv:
        select_only(config, state, now)
        return
    if not config.get("enabled") or now.date() > date.fromisoformat(config["stop_after"]):
        message = "# 机票监控已关闭或超过截止日期；未查询 API。\n"
        watch.OUT_DIR.mkdir(exist_ok=True)
        (watch.OUT_DIR / "watch-batch.md").write_text(message, encoding="utf-8")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(message)
        print(message)
        report_output(False)
        return
    active = watch.monitored_departure_dates(config)
    removed = watch.prune_retired_itineraries(state, active)
    if removed:
        print("Retired itinerary state removed: " + ", ".join(removed), flush=True)
    due = select_due_dates(config, {} if os.environ.get("FORCE_SCAN") == "true" else state, now)
    batch = []
    scanned_prices = set()
    fallback_needed = False
    watch.OUT_DIR.mkdir(exist_ok=True)
    if not due:
        if removed:
            watch.github_commit_state(state)
        print("No itinerary due. All remaining dates were checked recently; no API request.")
        report_output(False, due=False)
        return

    for i, dep in due:
        print("Checking overdue itinerary: " + dep, flush=True)
        try:
            watch.perform(config, state, index=i, live=True, notify=False)
            result_path = watch.OUT_DIR / "watch-result.json"
            if result_path.exists():
                outcome = json.loads(result_path.read_text(encoding="utf-8"))
                (watch.OUT_DIR / ("watch-" + dep + ".json")).write_text(
                    json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                text_path = watch.OUT_DIR / "watch-result.md"
                if text_path.exists():
                    (watch.OUT_DIR / ("watch-" + dep + ".md")).write_text(
                        text_path.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                outcome = {"status": "missing_output", "alert": False}
            channel = outcome.get("notification_channel")
            outbound_leg = outcome.get("outbound") if isinstance(outcome.get("outbound"), dict) else {}
            return_leg = outcome.get("return") if isinstance(outcome.get("return"), dict) else {}
            record = {
                "checked_at_bjt": datetime.now(BJT).isoformat(timespec="seconds"),
                "status": outcome.get("status"),
                "outbound_api_status": outcome.get("outbound_status"),
                "inbound_api_status": outcome.get("inbound_status"),
                "reference_total_cny": outcome.get("reference_sum_cny"),
                "return_date": outcome.get("return_date"),
                "outbound_flight": outbound_leg.get("flight"),
                "return_flight": return_leg.get("flight"),
                "outbound_airline": outbound_leg.get("airline"),
                "return_airline": return_leg.get("airline"),
                "outbound_price_cny": outbound_leg.get("price_cny_reference"),
                "return_price_cny": return_leg.get("price_cny_reference"),
                "outbound_url": outbound_leg.get("booking_url"),
                "return_url": return_leg.get("booking_url"),
                "taxes_verified": False,
                "baggage_verified": False,
                "notification_channel": channel,
                "query_diagnostics": outcome.get("query_diagnostics"),
                "data_gap": outcome.get("data_gap"),
                "annotations": outcome.get("annotations"),
            }
            if record["status"] == "priced_reference":
                # Preserve the last actual successful reference quote separately.
                # A later API failure does NOT erase it, but this historical
                # quote must NEVER be used as a live price-alert input.
                state.setdefault("last_valid_fares", {})[dep] = {
                    key: record.get(key) for key in (
                        "checked_at_bjt", "return_date", "reference_total_cny",
                        "outbound_flight", "return_flight",
                        "outbound_airline", "return_airline",
                        "outbound_price_cny", "return_price_cny",
                        "outbound_url", "return_url",
                    )
                }
                scanned_prices.add(dep)
            state.setdefault("last_scan_bjt", {})[dep] = record["checked_at_bjt"]
            state.setdefault("last_scan_results", {})[dep] = record
            note_quote_health(state, dep, record.get("status"), record["checked_at_bjt"])
            batch.append({"departure": dep, **record})
        except Exception as exc:
            # Do not mark as successfully checked; retry this date next run.
            batch.append({"departure": dep, "status": "runner_error", "error_type": type(exc).__name__})
            print("Scan failed for " + dep + ": " + type(exc).__name__, flush=True)

    active_dates = [dep for dep in active if date.fromisoformat(dep) >= now.date()]
    observed = datetime.now(BJT)
    fallback_needed = watch.notify_window_winners(config, state, scanned_prices, observed)
    alert_stamp = observed.isoformat(timespec="seconds")
    for item in batch:
        for payload in (state.get("window_alerts") or {}).values():
            if not isinstance(payload, dict):
                continue
            if payload.get("departure") == item.get("departure") and payload.get("last_alert_at_bjt") == alert_stamp:
                item["notification_channel"] = payload.get("delivery_channel")
    gaps = monitor_gaps(state, active_dates, observed)
    anomaly_email = False
    if not gaps:
        # Clear incident only on genuine complete recovery of all long gaps.
        state["anomaly_episode_active"] = False
    elif not anomaly_episode_active(state):
        if should_notify_anomaly(state, gaps, observed):
            anomaly_email = notify_anomaly(state, gaps, observed)
        # Also suppress additional alerts if a new incident started within the
        # daily quota guard. No repeat until full recovery is observed.
        state["anomaly_episode_active"] = True

    if removed or any(b.get("status") != "runner_error" for b in batch):
        watch.github_commit_state(state)

    timestamp = datetime.now(BJT).isoformat(timespec="seconds")
    completed = sum(1 for b in batch if b.get("status") not in ("runner_error", "missing_output"))
    incomplete = sum(1 for b in batch if b.get("status") not in ("priced_reference", "runner_error", "missing_output"))
    if gaps:
        health = "anomaly"
    elif incomplete or completed < len(batch):
        health = "degraded"
    else:
        health = "ok"
    records = {
        "health": health, "run_time_bjt": timestamp, "scanned": batch,
        "completed": completed, "incomplete": incomplete, "data_gap_dates": gaps,
    }
    (watch.OUT_DIR / "watch-batch.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 机票监控批次", "检查时间（北京时间）：" + timestamp, "本次检查 " + str(completed) + " 组；报价数据缺口 " + str(incomplete) + " 组。"]
    for record in batch:
        # Fare text lives in the one-combo-per-window section. These lines stay diagnostic.
        if config.get("rest_windows"):
            lines.append("- " + record["departure"] + ": " + record.get("status", "unknown") +
                         "；去程接口=" + str(record.get("outbound_api_status")) +
                         "；返程接口=" + str(record.get("inbound_api_status")))
            continue
        price = "；往返参考价 ¥" + str(record.get("reference_total_cny")) if record.get("reference_total_cny") else "；往返参考价：未取得"
        flights = ""
        if record.get("outbound_flight") or record.get("return_flight"):
            flights = (
                "；去程 " + watch.format_carrier(record.get("outbound_airline"), record.get("outbound_flight"))
                + " ¥" + str(record.get("outbound_price_cny"))
                + "；返程 " + watch.format_carrier(record.get("return_airline"), record.get("return_flight"))
                + " ¥" + str(record.get("return_price_cny"))
            )
        lines.append("- " + record["departure"] + ": " + record.get("status", "unknown") +
                     "；去程接口=" + str(record.get("outbound_api_status")) +
                     "；返程接口=" + str(record.get("inbound_api_status")) + flights + price)
    lines.append("status=1、缺返程或无法相加时，记为监控数据缺口。这不能说明没有航班，也不能说明价格高于预算。")
    lines.append("参考价来自 ticketPrice，税费、机建燃油、托运行李和雪具费用均未核实。")
    digest = watch.format_window_digest(config, state)
    if digest:
        lines.append(digest)
    if gaps:
        lines.append("监控异常：以下日期已长时间没有有效往返参考价：" + "、".join(gaps))
    # Historical quotes are informational only and never satisfy live price alerts.
    for item in batch:
        dep = item.get("departure")
        if item.get("status") == "incomplete_no_reliable_roundtrip_price":
            previous = (state.get("last_valid_fares") or {}).get(dep)
            if isinstance(previous, dict) and previous.get("reference_total_cny"):
                lines.append(
                    "- " + str(dep) + " 最近一次历史有效参考价：¥"
                    + str(previous["reference_total_cny"])
                    + "（" + str(previous.get("checked_at_bjt"))
                    + "，**非当前报价、不可用于触发低价提醒**）"
                )
    summary = "\n\n".join(lines) + "\n"
    (watch.OUT_DIR / "watch-batch.md").write_text(summary, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(summary)
    print(summary, flush=True)
    if health == "anomaly":
        print("::warning title=Fare monitor anomaly::No valid round-trip reference for an extended period. This is a data gap, not an over-budget result.")
    elif health == "degraded":
        print("::warning title=Fare query degraded::Incomplete quotes or query errors; see batch summary and artifacts.")
    report_output(fallback_needed, anomaly_email)
    if completed == 0:
        raise RuntimeError("All due itinerary checks failed; no coverage recorded")


if __name__ == "__main__":
    main()
