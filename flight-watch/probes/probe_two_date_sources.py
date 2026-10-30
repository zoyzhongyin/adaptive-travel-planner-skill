#!/usr/bin/env python3
"""One-off *read-only* fare-source verification, isolated from production monitor.

Tests public browser behavior for TFU/AAT on two exact dates. Never checks out,
uses credentials, rotates fingerprints, or bypasses site access controls.
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

LEGS = [("TFU", "AAT", "2026-12-09"), ("AAT", "TFU", "2026-12-14")]


def emit(source, leg, status, records=None, detail=""):
    print("PROBE_JSON " + json.dumps({
        "source": source,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "origin": leg[0],
        "destination": leg[1],
        "departure_date": leg[2],
        "status": status,
        "matches": (records or [])[:8],
        "total_matches": len(records or []),
        "detail": detail[:220],
        "taxes_verified": False,
        "bookability_verified": False,
    }, ensure_ascii=False), flush=True)


def run_ctrip():
    sys.path.insert(0, "/tmp/ctrip-ticket-crawler/browser_automation")
    from flight_crawler import FlightCrawler
    with FlightCrawler(headless=True) as crawler:
        for leg in LEGS:
            captured = []
            errors = []
            # Try airport code first; city-level CTU as fallback only, and
            # always validate segment airport TFU strictly.
            for depcode in ([leg[0], "CTU"] if leg[0] == "TFU" else [leg[0]]):
                try:
                    result = crawler.search(depcode, leg[1], leg[2],
                                            include_transfer=False,
                                            include_shared=True,
                                            timeout_ms=25000)
                    errors.append(f"{depcode}: {result.error or 'ok'}")
                    for f in result.flights:
                        segs = f.segments
                        if len(segs) != 1:
                            continue
                        s = segs[0]
                        if (s.departure_airport_code != leg[0] or
                            s.arrival_airport_code != leg[1] or
                            str(s.departure_time)[:10] != leg[2]):
                            continue
                        price = f.adult_price
                        if not isinstance(price, (int, float)) or price <= 0:
                            continue
                        captured.append({
                            "flight_number": s.flight_no,
                            "operating_flight": s.operate_flight_no,
                            "date": leg[2],
                            "origin": s.departure_airport_code,
                            "destination": s.arrival_airport_code,
                            "scheduled_departure": s.departure_time,
                            "price_cny": price,
                            "cabin": f.cabin,
                            "baggage_kg_claim": f.baggage_kg,
                            "ticket_count_claim": f.ticket_count,
                            "price_type": "provider_adultPrice_unverified_tax",
                        })
                except Exception as e:
                    errors.append(f"{depcode}: {type(e).__name__} {str(e)[:85]}")
                if captured:
                    break
            captured.sort(key=lambda x: x["price_cny"])
            emit("ctrip_browser", leg, "priced_reference" if captured else "no_valid_match",
                 captured, "; ".join(errors))


def run_flyclaw():
    sys.path.insert(0, "/tmp/FlyClaw")
    from sources.google_flights import GoogleFlightsSource
    from sources.skiplagged import SkiplaggedSource
    sources = [
        ("google_flights_fli", GoogleFlightsSource(timeout=12, retry=0)),
        ("skiplagged_rest", SkiplaggedSource(timeout=12, retry=0, mcp_enabled=False)),
    ]
    for name, source in sources:
        for leg in LEGS:
            try:
                recs = source.query_by_route(leg[0], leg[1], leg[2],
                                             cabin="economy", stops=0, limit=20)
                matches = []
                for row in recs:
                    date = str(row.get("scheduled_departure") or "")[:10]
                    ori = str(row.get("origin_iata") or "")
                    dst = str(row.get("destination_iata") or "")
                    price = row.get("price")
                    try: price = float(price)
                    except (TypeError, ValueError): continue
                    if (ori, dst, date) != leg or price <= 0:
                        continue
                    if row.get("stops") not in (None, 0, "0"):
                        continue
                    matches.append({
                        "flight_number": row.get("flight_number"),
                        "date": date, "origin": ori, "destination": dst,
                        "scheduled_departure": row.get("scheduled_departure"),
                        "price": price, "currency": row.get("currency"),
                        "cabin": row.get("cabin_class"),
                        "source": row.get("source"),
                        "price_type": "unverified_source_price",
                    })
                matches.sort(key=lambda x: x["price"])
                emit(name, leg, "priced_reference" if matches else "no_valid_match",
                     matches, f"raw_records={len(recs)}")
            except Exception as e:
                emit(name, leg, "query_error", [], f"{type(e).__name__}: {str(e)[:170]}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    arg = argparse.ArgumentParser()
    arg.add_argument("--source", choices=("ctrip", "flyclaw"), required=True)
    source = arg.parse_args().source
    try:
        (run_ctrip if source == "ctrip" else run_flyclaw)()
    except Exception as e:
        emit(source, ("TFU", "AAT", "2026-12-09"), "fatal_error",
             [], f"{type(e).__name__}: {str(e)[:170]}")
        raise
