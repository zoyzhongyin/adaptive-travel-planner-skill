"""Ctrip public-page reference as the primary fare source (2026-11-13).

FlyAI quota ran out (HTTP 402 usage_limit) and will not be topped up. When
``flyai_enabled`` is false the batch runner reads the latest public Ctrip
snapshot (flight-watch/ctrip-latest.json, produced by scripts/ctrip_snapshot.py)
instead of calling FlyAI. Thresholds and repeat-alert rules are unchanged:
the converted record goes through the same window/alert code as FlyAI did.

Only public listing pages are used. No login, no paid service, no booking.
Re-enable FlyAI by setting ``flyai_enabled`` back to true in config.json
(or FLYAI_ENABLED=true for a one-off run). No FlyAI code was removed.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CTRIP_PATH = ROOT / "flight-watch/ctrip-latest.json"
BJT = timezone(timedelta(hours=8))
SOURCE_ID = "ctrip_public_reference"
SOURCE_LABEL = "携程公开页面参考价"
SNAPSHOT_SOURCE = "ctrip_browser_public_listing"
DEFAULT_MAX_AGE_HOURS = 18
FLIGHT_RE = re.compile(r"[A-Z0-9]{2}\d{3,5}")
QUOTA_ERRORS = ("usage_limit", "trial_limit")
QUOTA_HTTP = (402, 429)


def flyai_enabled(config: dict, environ=None) -> bool:
    """config.json decides; FLYAI_ENABLED=true/false overrides for one run."""
    env = os.environ if environ is None else environ
    override = str(env.get("FLYAI_ENABLED") or "").strip().lower()
    if override in ("true", "1", "yes"):
        return True
    if override in ("false", "0", "no"):
        return False
    return bool(config.get("flyai_enabled", True))


def primary_source(config: dict, environ=None) -> str:
    return "flyai" if flyai_enabled(config, environ) else SOURCE_ID


def load_snapshot(path=None):
    try:
        return json.loads(Path(path or CTRIP_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def snapshot_valid(ctrip) -> bool:
    return (isinstance(ctrip, dict) and ctrip.get("schema_version") == 1
            and ctrip.get("source") == SNAPSHOT_SOURCE
            and ctrip.get("taxes_verified") is False
            and ctrip.get("bookability_verified") is False
            and ctrip.get("cabin_verified") is False
            and isinstance(ctrip.get("itineraries"), list))


def _parse_bjt(text):
    try:
        value = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=BJT)
    return value


def _money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite() or not (0 < amount < 50000):
        return None
    return amount


def _norm(amount: Decimal) -> str:
    return str(amount.quantize(Decimal("0.01")))


def _leg(row, day: str):
    if not isinstance(row, dict):
        return None
    flight = str(row.get("flight") or "").upper()
    price = _money(row.get("price_cny"))
    if not FLIGHT_RE.fullmatch(flight) or price is None:
        return None
    if not str(row.get("departure_time") or "").startswith(day):
        return None
    return {"flight": flight, "airline": str(row.get("airline") or row.get("carrier") or "")[:20],
            "price": price}


def search_url(origin: str, destination: str, day: str) -> str:
    """Public Ctrip one-way listing (no login). TFU is listed under Chengdu (CTU)."""
    city = {"TFU": "ctu"}.get(origin, origin.lower())
    dest = {"TFU": "ctu"}.get(destination, destination.lower())
    return ("https://flights.ctrip.com/online/list/oneway-" + city + "-" + dest
            + "?depdate=" + day + "&cabin=y_s&adult=1")


def ctrip_record(config: dict, ctrip, dep: str, now: datetime) -> dict:
    """Return a batch-runner record for one departure from the Ctrip snapshot.

    A missing, malformed, mismatched or stale itinerary is a data gap
    (status ``incomplete_no_reliable_roundtrip_price``) and can never trigger
    a price alert.
    """
    ret = (date.fromisoformat(dep) + timedelta(days=int(config["stay_nights"]))).isoformat()
    base = {
        "checked_at_bjt": now.astimezone(BJT).isoformat(timespec="seconds"),
        "data_source": SOURCE_ID,
        "data_source_label": SOURCE_LABEL,
        "source_generated_at_bjt": None,
        "source_checked_at_bjt": None,
        "return_date": ret,
        "outbound_api_status": None,
        "inbound_api_status": None,
        "taxes_verified": False,
        "baggage_verified": False,
        "notification_channel": None,
        "annotations": None,
    }

    def gap(reason: str) -> dict:
        return {**base, "status": "incomplete_no_reliable_roundtrip_price",
                "reference_total_cny": None, "data_gap": reason,
                "query_diagnostics": {"source": SOURCE_ID, "error": reason}}

    if not snapshot_valid(ctrip):
        return gap("ctrip_snapshot_missing_or_invalid")
    base["source_generated_at_bjt"] = str(ctrip.get("generated_at_bjt") or "")[:32] or None
    item = next((x for x in ctrip["itineraries"]
                 if isinstance(x, dict) and x.get("departure") == dep), None)
    if item is None:
        return gap("ctrip_itinerary_missing")
    if item.get("return_date") != ret:
        return gap("ctrip_return_date_mismatch")
    checked = _parse_bjt(item.get("checked_at_bjt"))
    if checked is None:
        return gap("ctrip_checked_at_invalid")
    base["source_checked_at_bjt"] = checked.astimezone(BJT).isoformat(timespec="seconds")
    max_age = timedelta(hours=float(config.get("ctrip_max_age_hours", DEFAULT_MAX_AGE_HOURS)))
    if checked > now + timedelta(minutes=10):
        return gap("ctrip_checked_at_in_future")
    if now - checked > max_age:
        return gap("ctrip_snapshot_stale")
    if item.get("status") != "priced_reference":
        return gap("ctrip_itinerary_incomplete")
    out = _leg(item.get("outbound"), dep)
    back = _leg(item.get("return"), ret)
    total = _money(item.get("total_cny"))
    if out is None or back is None or total is None:
        return gap("ctrip_itinerary_invalid")
    if out["price"] + back["price"] != total:
        return gap("ctrip_total_mismatch")
    return {
        **base,
        "status": "priced_reference",
        "reference_total_cny": _norm(total),
        "outbound_flight": out["flight"],
        "return_flight": back["flight"],
        "outbound_airline": out["airline"],
        "return_airline": back["airline"],
        "outbound_price_cny": _norm(out["price"]),
        "return_price_cny": _norm(back["price"]),
        "outbound_url": search_url(config.get("origin", "TFU"), config.get("destination", "AAT"), dep),
        "return_url": search_url(config.get("destination", "AAT"), config.get("origin", "TFU"), ret),
        "data_gap": None,
        "query_diagnostics": {"source": SOURCE_ID},
    }


def is_quota_record(record) -> bool:
    """True when a scan failed because a provider quota/rate limit (402/429) was hit."""
    if not isinstance(record, dict):
        return False
    diag = record.get("query_diagnostics")
    legs = []
    if isinstance(diag, dict):
        legs = [diag] + [v for v in diag.values() if isinstance(v, dict)]
    for leg in legs:
        if leg.get("error") in QUOTA_ERRORS:
            return True
        try:
            if int(leg.get("http_status") or 0) in QUOTA_HTTP:
                return True
        except (TypeError, ValueError):
            continue
    return False


def split_quota_gaps(state: dict, gaps: list) -> tuple[list, list]:
    """Separate quota-caused gaps (logged silently) from genuine data gaps."""
    results = state.get("last_scan_results") or {}
    quota = [dep for dep in gaps if is_quota_record(results.get(dep))]
    other = [dep for dep in gaps if dep not in quota]
    return quota, other
