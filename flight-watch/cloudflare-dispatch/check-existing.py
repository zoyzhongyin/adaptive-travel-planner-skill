#!/usr/bin/env python3
"""Fail closed before deployment: never create a replacement Worker."""
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()  # Remove accidental copy/paste boundary whitespace; never log value.
if any(ch.isspace() for ch in token):
    sys.exit("Deployment secret has internal whitespace/control characters. Replace the GitHub Actions secret with the unmodified single-line token.")
if not re.fullmatch(r"[a-fA-F0-9]{32}", account) or not token:
    sys.exit("Configure CLOUDFLARE_ACCOUNT_ID variable and CLOUDFLARE_API_TOKEN secret in GitHub Settings.")
url = f"https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts/altay-fare-cron/settings"
stage = "request_setup"
try:
    req = Request(url, headers={"Authorization": "Bearer " + token})
    stage = "http_connect"
    with urlopen(req, timeout=20) as response:
        stage = "json_decode"
        payload = json.load(response)
        stage = "response_shape"
except HTTPError as exc:
    sys.exit(f"Existing Worker check failed: HTTP {exc.code}; deployment stopped.")
except URLError as exc:
    cause = getattr(exc, "reason", None)
    typ = type(cause).__name__ if cause is not None else "unknown"
    # Log exception CLASS only; never print headers, token, request, or raw body.
    sys.exit("Existing Worker check failed: network transport category=" + typ + "; deployment stopped.")
except TimeoutError:
    sys.exit("Existing Worker check failed: request timeout; deployment stopped.")
except (ValueError, UnicodeDecodeError) as exc:
    sys.exit("Existing Worker check failed: stage=" + stage + ", error_type=" + type(exc).__name__ + "; deployment stopped.")
if payload.get("success") is not True:
    sys.exit("Cloudflare did not confirm existing Worker; deployment stopped.")
bindings = payload.get("result", {}).get("bindings", [])
if not any(b.get("name") == "GH_ACTIONS_TOKEN" and b.get("type") == "secret_text" for b in bindings):
    sys.exit("Add GH_ACTIONS_TOKEN as a secret on the EXISTING altay-fare-cron Worker before deployment.")
print("Existing altay-fare-cron and GH_ACTIONS_TOKEN secret binding confirmed; no secret values read.")
