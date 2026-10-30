#!/usr/bin/env python3
"""Low-rate public-page availability diagnostic for TFU ⇄ AAT.

Intentional restrictions:
- only public booking/search HTML URLs; no undocumented API, login, CAPTCHA,
  browser fingerprint spoofing, or rate-limit evasion;
- maximum six requests, one pass, 15s/request, 2s spacing;
- only report response status and structural hints, never raw HTML, cookies,
  booking links, source JS, or personal/private data;
- no alerts, no state writes, no pricing claims.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
import json
import re
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BJT = timezone(timedelta(hours=8))
PAIRS = [
    ("2026-12-09", "TFU", "AAT"),
    ("2026-12-14", "AAT", "TFU"),
    ("2026-12-18", "TFU", "AAT"),
    ("2026-12-23", "AAT", "TFU"),
]
FLIGHT_PATTERN = re.compile(r"\b(?:9C668[56]|3U657[3456]|CA250[56])\b", re.I)
UA = "AltayFareResearch/1.0 (personal low-volume public-page test)"

class Title(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.inside = False

    def handle_data(self, value):
        if self.inside:
            self.title += value[:100]

def public_page(url: str, *, timeout: int = 15) -> dict:
    """A status-only test; body snippets and query strings are never logged."""
    request = Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "").split(";")[0][:40]
            html = response.read(3_000_000).decode("utf-8", "replace")
            title = Title()
            title.feed(html[:300_000])
            return {
                "status": response.status,
                "final_host": urlparse(response.url).hostname,
                "type": content_type,
                "bytes_examined": len(html.encode("utf-8")),
                "has_nuxt_payload": "window.__NUXT__" in html,
                "has_flight_list_key": (
                    "flightLists" in html or "FlightInfoSimpleList" in html
                    or "getflightlist" in html.lower()
                ),
                "has_flight_number_text": bool(FLIGHT_PATTERN.search(html)),
                "page_title": re.sub(r"[\x00-\x1f]+", " ", title.title).strip()[:70],
                "pricing_verified": False,
            }
    except HTTPError as exc:
        return {"status": exc.code, "error": "http_error", "pricing_verified": False}
    except (URLError, TimeoutError) as exc:
        return {"status": None, "error": type(exc).__name__, "pricing_verified": False}

def probe() -> list[dict]:
    results = []
    for day, origin, dest in PAIRS:
        url = "https://www.ly.com/flights/itinerary/oneway/" + (
            origin.lower() + "-" + dest.lower()
        ) + "?date=" + day
        res = public_page(url)
        results.append({"provider": "tongcheng_public_page", "date": day,
                        "route": origin + "→" + dest, **res})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
        time.sleep(2)

    # SpringAirlines-Monitor's documented public booking-page pattern.
    # The repository verified only Japan-bound routes. These are experimental.
    for day, origin, dest in PAIRS[:2]:
        params = urlencode({"FDate": day, "ANum": "1", "CNum": "0",
                            "INum": "0", "SType": "0", "IfRet": "false", "MType": "0"})
        url = f"https://en.ch.com/flights/{origin}-{dest}.html?" + params
        res = public_page(url)
        results.append({"provider": "spring_public_booking_page", "date": day,
                        "route": origin + "→" + dest, **res})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
        time.sleep(2)

    return results

def main() -> None:
    results = probe()
    print("SUMMARY only metadata; not a valid fare or ticket price.", flush=True)
    import os
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("# 阿勒泰独立公共页面探针（仅一次）\n\n")
            fh.write("严格单次低频 GET，未调用未公开接口或规避验证码。不修改现有票价、微信和 Worker。\n\n")
            fh.write("| 来源 | 航段/日期 | HTTP | 页面线索 | 价格证据 |\n|---|---|---|---|---|\n")
            for r in results:
                status = str(r.get("status") or r.get("error") or "n/a")
                markers = "NUXT=" + str(r.get("has_nuxt_payload", False))
                markers += " / list=" + str(r.get("has_flight_list_key", False))
                markers += " / number=" + str(r.get("has_flight_number_text", False))
                fh.write(f"| {r['provider']} | {r['route']} {r['date']} | {status} | {markers} | 未验证 |\n")
            fh.write("\n**HTTP 200 或出现航班号，不代表获得真实机票价格。**\n\n")
            fh.write("完成时间（北京时间）：" + datetime.now(BJT).isoformat(timespec="seconds") + "\n")

if __name__ == "__main__":
    main()
