#!/usr/bin/env python3
"""Fail closed before deployment: never create a replacement Worker."""
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
if not re.fullmatch(r"[a-fA-F0-9]{32}", account) or not token:
    sys.exit("Configure CLOUDFLARE_ACCOUNT_ID variable and CLOUDFLARE_API_TOKEN secret in GitHub Settings.")
url = f"https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts/altay-fare-cron/settings"
try:
    with urlopen(Request(url, headers={"Authorization": "Bearer " + token}), timeout=20) as response:
        payload = json.load(response)
except HTTPError as exc:
    sys.exit(f"Existing Worker check failed: HTTP {exc.code}; deployment stopped.")
except (URLError, TimeoutError, ValueError):
    sys.exit("Existing Worker check failed: network or invalid response; deployment stopped.")
if payload.get("success") is not True:
    sys.exit("Cloudflare did not confirm existing Worker; deployment stopped.")
bindings = payload.get("result", {}).get("bindings", [])
if not any(b.get("name") == "GH_ACTIONS_TOKEN" and b.get("type") == "secret_text" for b in bindings):
    sys.exit("Add GH_ACTIONS_TOKEN as a secret on the EXISTING altay-fare-cron Worker before deployment.")
print("Existing altay-fare-cron and GH_ACTIONS_TOKEN secret binding confirmed; no secret values read.")
