#!/usr/bin/env python3
"""Query FlyAI one-way fares for a configurable date range; no personal data or booking."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from decimal import Decimal, InvalidOperation

OUT_DIR = Path("fare-results")
PAIR_LIMIT = 7


def checked_request(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    required = ("origin", "destination", "departure_start", "departure_end", "stay_nights")
    for key in required:
        if key not in obj:
            raise ValueError("Missing required request field: " + key)
    for key in ("origin", "destination"):
        value = obj[key]
        if not isinstance(value, str) or not re.fullmatch(r"[\w\u4e00-\u9fff -]{2,40}", value):
            raise ValueError("Invalid origin/destination; use an airport IATA code or city name")
        obj[key] = value.strip()
    start = dt.date.fromisoformat(obj["departure_start"])
    end = dt.date.fromisoformat(obj["departure_end"])
    if start > end or (end - start).days >= PAIR_LIMIT:
        raise ValueError("Date range must contain 1 to 7 dates")
    stay = obj["stay_nights"]
    if type(stay) is not int or not 1 <= stay <= 14:
        raise ValueError("stay_nights must be an integer from 1 to 14")
    if start < dt.date.today() or end > dt.date.today() + dt.timedelta(days=360):
        raise ValueError("Flight dates must be future dates within the coming 360 days")
    if obj["origin"].upper() == obj["destination"].upper():
        raise ValueError("Origin and destination must be different")
    obj["departure_start"] = start.isoformat()
    obj["departure_end"] = end.isoformat()
    obj["direct_preferred"] = obj.get("direct_preferred", True) is not False
    return obj


def parse_price(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        dec = Decimal(str(value).replace(",", "").replace("¥", "").strip())
        return dec if dec >= 0 and dec.is_finite() else None
    except InvalidOperation:
        return None


def route_option(item: dict, origin: str, destination: str) -> dict | None:
    journeys = item.get("journeys")
    if not isinstance(journeys, list) or len(journeys) != 1:
        return None
    segments = journeys[0].get("segments")
    if not isinstance(segments, list) or not segments:
        return None
    if not all(isinstance(s, dict) for s in segments):
        return None
    first, last = segments[0], segments[-1]
    start_code = str(first.get("depStationCode") or "")
    end_code = str(last.get("arrStationCode") or "")
    # Strictly match requested airport codes, when the request used IATA code.
    if re.fullmatch(r"[A-Z]{3}", origin.upper()) and start_code != origin.upper():
        return None
    if re.fullmatch(r"[A-Z]{3}", destination.upper()) and end_code != destination.upper():
        return None
    price = parse_price(item.get("ticketPrice"))
    if price is None:
        return None
    direct = len(segments) == 1 and str(journeys[0].get("journeyType", "")).strip() != "中转"
    legs = [
        {
            "flight": s.get("marketingTransportNo"),
            "airline": s.get("marketingTransportName"),
            "from": s.get("depStationCode"),
            "to": s.get("arrStationCode"),
            "departure": s.get("depDateTime"),
            "arrival": s.get("arrDateTime"),
        }
        for s in segments
    ]
    return {
        "price_cny_reference": str(price),
        "direct": direct,
        "start": start_code,
        "end": end_code,
        "departure": first.get("depDateTime"),
        "arrival": last.get("arrDateTime"),
        "legs": legs,
        "booking_url": item.get("jumpUrl"),
    }


def query(origin: str, destination: str, date: dt.date, file_stub: str) -> dict:
    cmd = [
        "flyai", "search-flight",
        "--origin", origin, "--destination", destination,
        "--dep-date", date.isoformat(), "--sort-type", "3",
    ]
    result = {"date": date.isoformat(), "from": origin, "to": destination}
    try:
        done = subprocess.run(cmd, text=True, capture_output=True, timeout=50, check=False)
        (OUT_DIR / (file_stub + ".json")).write_text(done.stdout, encoding="utf-8")
        (OUT_DIR / (file_stub + ".stderr")).write_text(done.stderr, encoding="utf-8")
        result["cli_exit"] = done.returncode
        data = json.loads(done.stdout)
        result["api_status"] = data.get("status")
        result["api_message"] = data.get("message")
        result["platform_message"] = data.get("systemMessage")
        entries = data.get("data", {}).get("itemList", []) if isinstance(data.get("data"), dict) else []
        options = [route_option(entry, origin, destination) for entry in entries if isinstance(entry, dict)]
        result["offers"] = sorted((o for o in options if o is not None), key=lambda x: Decimal(x["price_cny_reference"]))
        result["raw_offer_count"] = len(entries)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)[:250]
        result["offers"] = []
    return result


def brief_option(offer: dict) -> str:
    segs = offer["legs"]
    routing = " / ".join(str(s["flight"] or "?") for s in segs)
    return (f"¥{offer['price_cny_reference']} ({'直飞' if offer['direct'] else '中转'})"
            f" {offer['departure']} → {offer['arrival']}; {routing}")


def summarize(req: dict, results: list[dict]) -> str:
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 机票查询结果（飞猪 FlyAI 接口）",
        f"查询时间：{now}（北京时间）",
        f"航线：{req['origin']} ⇄ {req['destination']}；出发范围 {req['departure_start']} 至 {req['departure_end']}；住宿 {req['stay_nights']} 晚",
        "**注意：价格来自 FlyAI ticketPrice 字段，是单程参考报价，并非已核实的最终含税或包含托运行李的成交价。**",
        "体验模式结果可能不完整；返回 status=1 或 0 条不能证明无航班。最终须打开平台核实票价、剩余座位、退改规则与雪具行李费用。",
        "",
    ]
    summary = []
    for pair in results:
        depart = pair["outbound"]
        ret = pair["inbound"]
        lines.append(f"## {pair['departure']} 出发 / {pair['return']} 返回")
        for name, leg in (("去程", depart), ("返程", ret)):
            lines.append(f"- {name}：API状态={leg.get('api_status', '不可用')}，原始结果={leg.get('raw_offer_count',0)}条")
            if leg.get("error"):
                lines.append(f"  - 错误：{leg['error']}")
            direct = [v for v in leg["offers"] if v["direct"]]
            cheapest = leg["offers"][:1]
            if direct:
                lines.append("  - 最低直飞：" + brief_option(direct[0]))
            if cheapest:
                lines.append("  - 最低已返回报价：" + brief_option(cheapest[0]))
        possible = bool(depart["offers"] and ret["offers"])
        both_direct_out = [x for x in depart["offers"] if x["direct"]]
        both_direct_in = [x for x in ret["offers"] if x["direct"]]
        if both_direct_out and both_direct_in:
            a, b = both_direct_out[0], both_direct_in[0]
            price = Decimal(a["price_cny_reference"]) + Decimal(b["price_cny_reference"])
            lines.append(f"- **最低已返回双程直飞参考报价合计：¥{price}**（两张单程相加，非已核实往返出票价）")
            lines.append(f"  - 去程：[预订入口]({a['booking_url']}) / 返程：[预订入口]({b['booking_url']})")
            summary.append({"departure": pair["departure"], "return": pair["return"], "direct_combined_reference_cny": str(price)})
        if possible:
            a, b = depart["offers"][0], ret["offers"][0]
            price = Decimal(a["price_cny_reference"]) + Decimal(b["price_cny_reference"])
            lines.append(f"- 最低已返回双程参考报价合计：¥{price}（可能中转或过夜，未核实可联程购买）")
        if not possible:
            lines.append("- 有单程未能取得有效报价；无法计算往返价格。")
        lines.append("")
    (OUT_DIR / "summary.json").write_text(json.dumps({"request": req, "pairs": results, "direct_comparisons": summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    OUT_DIR.mkdir(exist_ok=True)
    req = checked_request(args.request)
    (OUT_DIR / "request.json").write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
    start = dt.date.fromisoformat(req["departure_start"])
    end = dt.date.fromisoformat(req["departure_end"])
    results = []
    for day_offset in range((end - start).days + 1):
        dep = start + dt.timedelta(days=day_offset)
        ret = dep + dt.timedelta(days=req["stay_nights"])
        outward = query(req["origin"], req["destination"], dep, f"{dep}_outbound")
        inward = query(req["destination"], req["origin"], ret, f"{ret}_return")
        results.append({"departure": dep.isoformat(), "return": ret.isoformat(), "outbound": outward, "inbound": inward})
    summary = summarize(req, results)
    print(summary)
    (OUT_DIR / "summary.md").write_text(summary, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(summary)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError) as exc:
        print(f"Request validation failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
