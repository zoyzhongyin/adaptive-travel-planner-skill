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
import time
from decimal import Decimal, InvalidOperation

OUT_DIR = Path("fare-results")
PAIR_LIMIT = 7
# Official search-flight sort codes. Sort 3 is price-ascending and is the
# call that historically returns status=1 "搜索机票低价行业失败". Later
# attempts change sort, then city name, still on the same official API.
RETRY_PAUSES_SECONDS = (2, 4)
AIRPORT_CITY_NAMES = {"TFU": "成都", "AAT": "阿勒泰"}


def checked_request(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    required = ("origin", "destination", "stay_nights")
    for key in required:
        if key not in obj:
            raise ValueError("Missing required request field: " + key)
    for key in ("origin", "destination"):
        value = obj[key]
        if not isinstance(value, str) or not re.fullmatch(r"[\w\u4e00-\u9fff -]{2,40}", value):
            raise ValueError("Invalid origin/destination; use an airport IATA code or city name")
        obj[key] = value.strip()
    if "departure_dates" in obj:
        days = obj["departure_dates"]
        if not isinstance(days, list) or not 1 <= len(days) <= PAIR_LIMIT or any(not isinstance(day, str) for day in days):
            raise ValueError("departure_dates must be an array containing 1 to 7 ISO dates")
        dates = sorted({dt.date.fromisoformat(day) for day in days})
        if len(dates) != len(days):
            raise ValueError("departure_dates must not have duplicate dates")
        start, end = dates[0], dates[-1]
        obj["departure_dates"] = [day.isoformat() for day in dates]
    else:
        for key in ("departure_start", "departure_end"):
            if key not in obj:
                raise ValueError("Missing required request field: " + key)
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


def city_label(place: str) -> str:
    return AIRPORT_CITY_NAMES.get(place.upper(), place)


def attempt_plan(origin: str, destination: str, direct_only: bool) -> list[dict]:
    """Three official FlyAI shapes. Stop early once a usable quote is parsed."""
    return [
        {"label": "iata_price_asc", "origin": origin, "destination": destination, "sort_type": "3", "journey_type": None},
        {"label": "iata_direct_first", "origin": origin, "destination": destination, "sort_type": "8", "journey_type": None},
        {
            "label": "city_direct_first",
            "origin": city_label(origin),
            "destination": city_label(destination),
            "sort_type": "8",
            "journey_type": "1" if direct_only else None,
        },
    ]


def build_search_command(spec: dict, date: dt.date, seat_class_name: str | None = None) -> list[str]:
    cmd = [
        "flyai", "search-flight",
        "--origin", spec["origin"], "--destination", spec["destination"],
        "--dep-date", date.isoformat(), "--sort-type", spec["sort_type"],
    ]
    if spec.get("journey_type"):
        cmd.extend(["--journey-type", spec["journey_type"]])
    # search-flight has no adults/passenger flag. Cabin is the supported party control.
    if seat_class_name:
        cmd.extend(["--seat-class-name", seat_class_name])
    return cmd


def route_option(item: dict, origin: str, destination: str, expected_date: dt.date | None = None) -> dict | None:
    journeys = item.get("journeys")
    if not isinstance(journeys, list) or len(journeys) != 1 or not isinstance(journeys[0], dict):
        return None
    segments = journeys[0].get("segments")
    if not isinstance(segments, list) or not segments:
        return None
    if not all(isinstance(s, dict) for s in segments):
        return None
    if any(s.get("transportType") not in (None, "", "飞机") for s in segments):
        return None
    first, last = segments[0], segments[-1]
    start_code = str(first.get("depStationCode") or "")
    end_code = str(last.get("arrStationCode") or "")
    # Strictly match requested airport codes, when the request used IATA code.
    if re.fullmatch(r"[A-Z]{3}", origin.upper()) and start_code.upper() != origin.upper():
        return None
    if re.fullmatch(r"[A-Z]{3}", destination.upper()) and end_code.upper() != destination.upper():
        return None
    departure_text = str(first.get("depDateTime") or "")
    if expected_date is not None and not departure_text.startswith(expected_date.isoformat()):
        return None
    # adultPrice is a different, unverified field. Only ticketPrice is a reference fare.
    price = parse_price(item.get("ticketPrice"))
    if price is None or price <= 0:
        return None
    flight_no = str(first.get("marketingTransportNo") or "").strip()
    stops = first.get("stopInfos")
    has_stop = isinstance(stops, (list, dict)) and len(stops) > 0
    direct = (
        len(segments) == 1
        and str(journeys[0].get("journeyType") or "").strip() != "中转"
        and not has_stop
        and bool(flight_no)
    )
    legs = [
        {
            "flight": s.get("marketingTransportNo"),
            "airline": s.get("marketingTransportName"),
            "seat_class": s.get("seatClassName"),
            "from": s.get("depStationCode"),
            "to": s.get("arrStationCode"),
            "departure": s.get("depDateTime"),
            "arrival": s.get("arrDateTime"),
        }
        for s in segments
    ]
    return {
        "price_cny_reference": str(price),
        "price_basis": "ticketPrice_reference",
        "taxes_verified": False,
        "baggage_verified": False,
        "ski_equipment_verified": False,
        "direct": direct,
        "start": start_code,
        "end": end_code,
        "departure": first.get("depDateTime"),
        "arrival": last.get("arrDateTime"),
        "legs": legs,
        "booking_url": item.get("jumpUrl"),
    }


def interpret_response(stdout: str, origin: str, destination: str, expected_date: dt.date | None) -> dict:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return {"offers": [], "raw_offer_count": 0, "error": "JSONDecodeError"}
    if not isinstance(data, dict):
        return {"offers": [], "raw_offer_count": 0, "error": "ResponseNotObject"}
    result = {
        "api_status": data.get("status"),
        "api_message": data.get("message"),
        "platform_message": data.get("systemMessage"),
    }
    payload = data.get("data")
    entries = payload.get("itemList", []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        entries = []
    options = []
    for entry in entries:
        if isinstance(entry, dict):
            parsed = route_option(entry, origin, destination, expected_date)
            if parsed is not None:
                options.append(parsed)
    result["offers"] = sorted(options, key=lambda x: Decimal(x["price_cny_reference"]))
    result["raw_offer_count"] = len(entries)
    return result


def offer_matches_cabin(offer: dict, seat_class_name: str | None) -> bool:
    """Keep unlabeled offers. Drop a labeled cabin that is not the one we asked for.

    Recorded FlyAI payloads often omit seatClassName. Filtering those out would
    hide every direct, including non-9C flights. The CLI flag is the primary
    cabin control; this only rejects an explicit other cabin.
    """
    if not seat_class_name:
        return True
    labels = []
    for leg in offer.get("legs") or []:
        label = str((leg or {}).get("seat_class") or "").strip()
        if label:
            labels.append(label)
    if not labels:
        return True
    return all(label == seat_class_name for label in labels)


def leg_ready(result: dict, direct_only: bool) -> bool:
    """A usable one-way quote. status=1 or a missing direct leg is not ready."""
    if result.get("error"):
        return False
    offers = result.get("offers") or []
    if direct_only:
        return any(offer.get("direct") for offer in offers)
    return bool(offers) and result.get("api_status") == 0


def _prefer(candidate: dict, current: dict | None, direct_only: bool) -> bool:
    if current is None:
        return True
    if leg_ready(candidate, direct_only) and not leg_ready(current, direct_only):
        return True
    if leg_ready(current, direct_only):
        return False
    return len(candidate.get("offers") or []) >= len(current.get("offers") or [])


def default_runner(cmd: list[str]) -> tuple[int, str, str]:
    done = subprocess.run(cmd, text=True, capture_output=True, timeout=30, check=False)
    return done.returncode, done.stdout, done.stderr


def query(origin: str, destination: str, date: dt.date, file_stub: str, *, direct_only: bool = False,
          max_attempts: int | None = None, runner=None, sleeper=None,
          seat_class_name: str | None = None) -> dict:
    limit = 3 if max_attempts is None else max(1, min(3, int(max_attempts)))
    plan = attempt_plan(origin, destination, direct_only)[:limit]
    run = runner or default_runner
    pause = sleeper or time.sleep
    OUT_DIR.mkdir(exist_ok=True)
    chosen = None
    history = []
    for index, spec in enumerate(plan):
        cmd = build_search_command(spec, date, seat_class_name)
        parsed: dict
        cli_exit = None
        stdout = ""
        stderr = ""
        try:
            cli_exit, stdout, stderr = run(cmd)
            parsed = interpret_response(stdout, origin, destination, date)
            if seat_class_name:
                parsed["offers"] = [
                    offer for offer in (parsed.get("offers") or [])
                    if offer_matches_cabin(offer, seat_class_name)
                ]
                parsed["seat_class_filter"] = seat_class_name
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            parsed = {"offers": [], "raw_offer_count": 0, "error": type(exc).__name__}
        label = spec["label"]
        (OUT_DIR / (file_stub + "_" + label + ".json")).write_text(stdout or "", encoding="utf-8")
        if stderr:
            (OUT_DIR / (file_stub + "_" + label + ".stderr")).write_text(stderr, encoding="utf-8")
        history.append({
            "label": label,
            "cli_exit": cli_exit,
            "api_status": parsed.get("api_status"),
            "raw_offer_count": parsed.get("raw_offer_count", 0),
            "api_message": parsed.get("api_message"),
            "error": parsed.get("error"),
        })
        candidate = {
            "date": date.isoformat(),
            "from": origin,
            "to": destination,
            "cli_exit": cli_exit,
            "query_strategy": label,
            **parsed,
        }
        if _prefer(candidate, chosen, direct_only):
            chosen = candidate
            (OUT_DIR / (file_stub + ".json")).write_text(stdout or "", encoding="utf-8")
            (OUT_DIR / (file_stub + ".stderr")).write_text(stderr or "", encoding="utf-8")
        if chosen is not None and leg_ready(chosen, direct_only):
            break
        if index < len(plan) - 1:
            pause(RETRY_PAUSES_SECONDS[min(index, len(RETRY_PAUSES_SECONDS) - 1)])
    if chosen is None:
        chosen = {
            "date": date.isoformat(), "from": origin, "to": destination,
            "offers": [], "raw_offer_count": 0, "error": "NoAttempt",
        }
    chosen["attempts"] = history
    return chosen


def brief_option(offer: dict) -> str:
    segs = offer["legs"]
    routing = " / ".join(str(s["flight"] or "?") for s in segs)
    return (f"¥{offer['price_cny_reference']} ({'直飞' if offer['direct'] else '中转'})"
            f" {offer['departure']} → {offer['arrival']}; {routing}")


def summarize(req: dict, results: list[dict]) -> str:
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    date_text = "、".join(req["departure_dates"]) if "departure_dates" in req else f"{req['departure_start']} 至 {req['departure_end']}"
    lines = [
        "# 机票查询结果（飞猪 FlyAI 接口）",
        f"查询时间：{now}（北京时间）",
        f"航线：{req['origin']} ⇄ {req['destination']}；出发日期 {date_text}；住宿 {req['stay_nights']} 晚",
        "**注意：价格来自 FlyAI ticketPrice 字段，是单程参考报价，并非已核实的最终含税或包含托运行李的成交价。税费、托运行李、雪具费用均未核实。**",
        "status=1、超时或 0 条有效报价是数据缺口。单程会换官方排序和城市名重试。仍失败时不能判断为没有航班，也不能判断为价格高于预算。",
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
            # Route-specific hypothetical budget, NOT a verified checkout quote.
            # Sources: Spring Airlines 2026-08-18 baggage table (2000-2999 km),
            # official October 2026 domestic fuel charge (90 CNY per >800km leg)
            # and domestic adult passenger civil aviation development fee (50 CNY/leg).
            if (req["origin"].upper(), req["destination"].upper()) == ("TFU", "AAT") and any(str(s.get("flight") or "").upper().startswith("9C") for s in b["legs"]):
                baggage_20kg = Decimal("159")
                fee_each_leg = Decimal("140")  # hypothetical 50 + 90, if NOT included
                incl = price + baggage_20kg
                excl = incl + fee_each_leg * 2
                lines.append("  - **费用敏感性示例，非实际含税报价：**按春秋返程基础票不含托运、另提前购买20kg行李（+159元）假设：")
                lines.append(f"    - 若 FlyAI 报价已包含机建及燃油：¥{incl}（仅加20kg行李）")
                lines.append(f"    - 若 FlyAI 两段报价均未包含机建及燃油：¥{excl}（再加每段50元民航发展基金与90元燃油费）")
                lines.append("    - 这两种是假设情景，**不是报价区间或价格承诺**。不可重复添加已含税费。春秋票型是否含行李、川航实际托运额度、滑雪板尺寸/手续费、平台服务费，必须以订单确认为准。")
                lines.append("    - 规则依据：[春秋2026行李价格](https://news.springairlines.cn/news/2026-06-16-00-00.html)、[燃油附加费通知](https://webresource.airchina.com.cn/zh-CN/content/c/2026-10-08/30592.shtml)、[财政部民航收费规定](https://www.mof.gov.cn/gkml/caizhengwengao/caizhengbuwengao2008/caizhengbuwengao20083/200805/t20080519_29156.htm)。")
                lines.append("    - 当前飞猪预订链接会跳转 login.taobao.com，自动程序不能查看登录后的结算页面。")
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
    if "departure_dates" in req:
        departure_days = [dt.date.fromisoformat(day) for day in req["departure_dates"]]
    else:
        start = dt.date.fromisoformat(req["departure_start"])
        end = dt.date.fromisoformat(req["departure_end"])
        departure_days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    results = []
    for dep in departure_days:
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
