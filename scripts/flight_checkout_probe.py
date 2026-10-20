#!/usr/bin/env python3
"""Non-booking diagnostics of public FlyAI booking URLs.

Never logs cookies, personal data, full HTML, or credentials.
No claims of checkout prices from snippets or redirects.
"""
from __future__ import annotations
import datetime as dt
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib import request, parse, error

ALLOWED_DOMAINS = ("router.feizhu.com", "feizhu.com", "fliggy.com", "outfliggys.m.taobao.com")
MAX_BYTES = 150000


def allowed(url):
    parts = parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == domain or host.endswith("." + domain) for domain in ALLOWED_DOMAINS)


class RedirectLimiter(request.HTTPRedirectHandler):
    def __init__(self):
        self.route = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.route.append((code, parse.urlsplit(newurl).hostname or "unknown"))
        if not allowed(newurl) or len(self.route) > 5:
            raise error.HTTPError(newurl, 470, "Redirect leaves recognized travel platform / too many redirects", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.words = []
        self.ignore = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignore += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.ignore = max(0, self.ignore - 1)

    def handle_data(self, data):
        if not self.ignore and data.strip():
            self.words.append(data.strip())


def check(url):
    if not allowed(url):
        return {"state": "not_checked", "reason": "Unexpected domain or invalid URL"}
    redirects = RedirectLimiter()
    opener = request.build_opener(redirects)
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"})
    try:
        with opener.open(req, timeout=15) as res:
            body = res.read(MAX_BYTES)
            typ = res.headers.get("Content-Type", "")
            final_host = parse.urlsplit(res.geturl()).hostname
            summary = {"http_status": res.status, "final_host": final_host, "content_type": typ.split(";")[0], "redirect_hosts": redirects.route, "body_bytes_sampled": len(body)}
            if "html" in typ.lower():
                doc = VisibleText()
                doc.feed(body.decode("utf-8", "replace"))
                visible = " ".join(doc.words)
                summary["has_login_prompt"] = any(t in visible for t in ("登录", "注册", "扫码登录", "Sign in", "Log in"))
                summary["has_checkout_terms"] = any(t in visible for t in ("订单总额", "实付款", "总支付", "机建燃油", "含税总价", "订单确认"))
                summary["public_text_chars"] = len(visible)
                summary["verified_all_in_fare"] = False
            else:
                summary["verified_all_in_fare"] = False
            return summary
    except Exception as exc:
        return {"state": "not_accessible", "reason": type(exc).__name__ + ": " + str(exc)[:150], "redirect_hosts": redirects.route, "verified_all_in_fare": False}


def main():
    path = Path("fare-results/summary.json")
    if not path.exists():
        print("Missing fare-results/summary.json, nothing to probe")
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    lines = ["# Public flight booking-link test (does not book or submit any passenger data)", "", "A redirect/page response alone cannot establish final checkout cost.", ""]
    for pair in payload.get("pairs", []):
        for side in ("outbound", "inbound"):
            opts = pair.get(side, {}).get("offers", [])
            direct = next((o for o in opts if o.get("direct") and o.get("booking_url")), None)
            if not direct:
                continue
            info = check(direct["booking_url"])
            lines.append(f"## {pair['departure']} / {pair['return']} / {side}")
            lines.append(f"- Flight: {direct['legs'][0].get('flight')}, raw ticketPrice: CNY {direct['price_cny_reference']}")
            lines.append(f"- Booking landing result: {json.dumps(info, ensure_ascii=False)}")
            lines.append("- Checkout taxes, baggage and inventory: **not verified** unless a named independent checkout confirmation can be observed.")
            lines.append("")
    output = "\n".join(lines)
    print(output)
    Path("fare-results/booking_link_diagnostics.md").write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
