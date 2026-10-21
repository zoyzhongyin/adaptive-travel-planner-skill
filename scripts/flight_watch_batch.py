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

BJT = timezone(timedelta(hours=8))


def select_due_dates(config: dict, state: dict, now: datetime) -> list[tuple[int, str]]:
    dates = config["departure_dates"]
    last = state.get("last_scan_bjt", {})
    interval = int(config.get("each_pair_interval_minutes", 90))
    cap = int(config.get("max_pairs_per_run", 3))
    if not (15 <= interval <= 1440 and 1 <= cap <= 7):
        raise ValueError("Invalid per-pair scan interval or batch-size")
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
        if last_time is None or (now - last_time) >= timedelta(minutes=interval):
            due.append((last_time or datetime(2000, 1, 1, tzinfo=BJT), i, dep))
    due.sort(key=lambda item: (item[0], item[2]))
    return [(i, dep) for _, i, dep in due[:cap]]


def report_output(value):
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as stream:
            stream.write("price_alert=" + ("true" if value else "false") + "\n")


def main():
    config = watch.json_read(watch.CONFIG_PATH)
    state = watch.json_read(watch.STATE_PATH)
    now = datetime.now(BJT)
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
    due = select_due_dates(config, state, now)
    batch = []
    fallback_needed = False
    watch.OUT_DIR.mkdir(exist_ok=True)
    if not due:
        print("No itinerary due. All remaining dates were checked recently; no API request.")
        report_output(False)
        return

    for i, dep in due:
        print("Checking overdue itinerary: " + dep, flush=True)
        try:
            hit = watch.perform(config, state, index=i, live=True)
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
            if hit and channel != "wechat":
                fallback_needed = True
            record = {
                "checked_at_bjt": datetime.now(BJT).isoformat(timespec="seconds"),
                "status": outcome.get("status"),
                "outbound_api_status": outcome.get("outbound_status"),
                "inbound_api_status": outcome.get("inbound_status"),
                "reference_total_cny": outcome.get("reference_sum_cny"),
                "notification_channel": channel,
            }
            state.setdefault("last_scan_bjt", {})[dep] = record["checked_at_bjt"]
            state.setdefault("last_scan_results", {})[dep] = record
            batch.append({"departure": dep, **record})
        except Exception as exc:
            # Do not mark as successfully checked; retry this date next run.
            batch.append({"departure": dep, "status": "runner_error", "error_type": type(exc).__name__})
            print("Scan failed for " + dep + ": " + type(exc).__name__, flush=True)

    if any(b.get("status") != "runner_error" for b in batch):
        watch.github_commit_state(state)

    timestamp = datetime.now(BJT).isoformat(timespec="seconds")
    completed = sum(1 for b in batch if b.get("status") != "runner_error")
    incomplete = sum(1 for b in batch if b.get("status") == "incomplete_no_reliable_roundtrip_price")
    records = {"run_time_bjt": timestamp, "scanned": batch, "completed": completed, "incomplete": incomplete}
    (watch.OUT_DIR / "watch-batch.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 机票监控批次", "检查时间（北京时间）：" + timestamp, "本次检查 " + str(completed) + " 组；报价不全 " + str(incomplete) + " 组。"]
    for record in batch:
        lines.append("- " + record["departure"] + ": " + record.get("status", "unknown") +
                     "；去程接口=" + str(record.get("outbound_api_status")) +
                     "；返程接口=" + str(record.get("inbound_api_status")) +
                     ("；往返参考价 ¥" + str(record.get("reference_total_cny")) if record.get("reference_total_cny") else ""))
    lines.append("status=1 或无完整两段报价表示接口未提供足够信息，不能推断无航班。")
    summary = "\n\n".join(lines) + "\n"
    (watch.OUT_DIR / "watch-batch.md").write_text(summary, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(summary)
    print(summary, flush=True)
    report_output(fallback_needed)
    if completed == 0:
        raise RuntimeError("All due itinerary checks failed; no coverage recorded")


if __name__ == "__main__":
    main()
