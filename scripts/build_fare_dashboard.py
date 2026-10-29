#!/usr/bin/env python3
"""Publish a deliberately public, sanitized fare dashboard snapshot.

No GH, FlyAI, ServerChan, Cloudflare credentials or monitoring diagnostics
are included in the generated Worker bundle. Never expose state.json raw.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from urllib import request, error

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "flight-watch/dashboard/index.html"
WORKER = ROOT / "flight-watch/cloudflare-dispatch"
STATE_PATH = ROOT / "flight-watch/state.json"
CONFIG_PATH = ROOT / "flight-watch/config.json"
PUBLIC_URL = "https://altay-fare-cron.zoyzhongyin.workers.dev/api/fares"
BJT = timezone(timedelta(hours=8))
MAX_PUBLIC_FIELDS = ("checked_at_bjt", "reference_total_cny", "status",
                     "outbound_price_cny", "return_price_cny",
                     "outbound_airline", "return_airline",
                     "outbound_flight", "return_flight")
HISTORY_FIELDS = ("checked_at_bjt", "reference_total_cny")

def fetch_github_state() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo or "/" not in repo:
        raise RuntimeError("GitHub Actions token/repository missing")
    url = "https://api.github.com/repos/" + repo + "/contents/flight-watch/state.json"
    req = request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "AltayPublicDashboard/1.0",
    })
    with request.urlopen(req, timeout=15) as response:
        blob = json.load(response)
    return json.loads(base64.b64decode(blob["content"]).decode("utf-8"))

def clean_text(value, max_len=80):
    return str(value)[:max_len] if value is not None else None

def clean_money(value):
    if value is None or value == "":
        return None
    from decimal import Decimal, InvalidOperation
    try:
        d = Decimal(str(value))
        if d.is_finite() and 0 <= d < 1_000_000:
            return str(d)
    except (InvalidOperation, ValueError):
        pass
    return None

def snapshot(config: dict, state: dict) -> dict:
    windows = [
        {"id": str(w["id"]), "start": str(w["start"]), "end": str(w["end"])}
        for w in config["rest_windows"]
    ]
    checks = state.get("last_scan_results") or {}
    historic = state.get("last_valid_fares") or {}
    result = []
    for dep in config["departure_dates"]:
        window = next((w["id"] for w in windows if w["start"] <= dep <= w["end"]), None)
        if window is None:
            raise ValueError("Monitored departure date outside rest window")
        row = checks.get(dep) or {}
        prior = historic.get(dep) or {}
        valid = row.get("status") == "priced_reference" and clean_money(row.get("reference_total_cny")) is not None
        result.append({
            "departure": dep,
            "return_date": clean_text(row.get("return_date"), 10) or (
                datetime.fromisoformat(dep).date()+timedelta(days=int(config["stay_nights"]))
            ).isoformat(),
            "window_id": window,
            "checked_at_bjt": clean_text(row.get("checked_at_bjt"), 32),
            "status": "priced_reference" if valid else "incomplete",
            "total_cny": clean_money(row.get("reference_total_cny")) if valid else None,
            "outbound_price_cny": clean_money(row.get("outbound_price_cny")),
            "return_price_cny": clean_money(row.get("return_price_cny")),
            "outbound_airline": clean_text(row.get("outbound_airline"), 40),
            "return_airline": clean_text(row.get("return_airline"), 40),
            "outbound_flight": clean_text(row.get("outbound_flight"), 20),
            "return_flight": clean_text(row.get("return_flight"), 20),
            "last_valid": {
                "checked_at_bjt": clean_text(prior.get("checked_at_bjt"), 32),
                "total_cny": clean_money(prior.get("reference_total_cny")),
            } if prior and clean_money(prior.get("reference_total_cny")) else None,
        })
    scanned = [x["checked_at_bjt"] for x in result if x.get("checked_at_bjt")]
    return {
        "schema_version": 1,
        "generated_at_bjt": datetime.now(BJT).isoformat(timespec="seconds"),
        "most_recent_check_bjt": max(scanned) if scanned else None,
        "origin": "TFU", "destination": "AAT",
        "alert_price_cny": int(config["alert_price_cny"]),
        "ideal_price_cny": int(config["ideal_price_cny"]),
        "stay_nights": int(config["stay_nights"]),
        "roster_tentative": True,
        "windows": windows,
        "itineraries": result,
    }

def needs_deploy(current: dict, *, min_minutes: int=45) -> bool:
    try:
        with request.urlopen(request.Request(PUBLIC_URL, headers={"User-Agent":"AltayDashboardPublisher/1.0"}),
                             timeout=9) as response:
            previous = json.load(response)
        latest_time = previous.get("generated_at_bjt")
        if not latest_time:
            return True
        age = datetime.now(BJT) - datetime.fromisoformat(latest_time)
        if age < timedelta(minutes=min_minutes):
            return False
        return previous.get("most_recent_check_bjt") != current.get("most_recent_check_bjt")
    except (error.URLError, ValueError, TimeoutError):
        return True

def build(*, github: bool, check_stale: bool) -> bool:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    state = fetch_github_state() if github else json.loads(STATE_PATH.read_text(encoding="utf-8"))
    public = snapshot(config, state)
    deploy = not check_stale or needs_deploy(public)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output,"a",encoding="utf-8") as stream:
            stream.write("publish="+("true" if deploy else "false")+"\n")
    if not deploy:
        print("Dashboard skipped: public snapshot is recent or no newer completed scan.")
        return False
    html = DASHBOARD.read_text(encoding="utf-8")
    (WORKER/"dashboard-page.mjs").write_text(
        "export const DASHBOARD_HTML = " + json.dumps(html, ensure_ascii=True) + ";\n", encoding="utf-8"
    )
    (WORKER/"dashboard-data.mjs").write_text(
        "export const PUBLIC_SNAPSHOT = " + json.dumps(public, ensure_ascii=True, separators=(",",":")) + ";\n",
        encoding="utf-8"
    )
    print("Sanitized dashboard prepared: "+str(len(public["itineraries"]))+
          " dates; most recent successful scan stamp: "+str(public["most_recent_check_bjt"]))
    return True

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--github", action="store_true")
    parser.add_argument("--only-if-new", action="store_true")
    args=parser.parse_args()
    build(github=args.github,check_stale=args.only_if_new)

if __name__=="__main__":
    main()
