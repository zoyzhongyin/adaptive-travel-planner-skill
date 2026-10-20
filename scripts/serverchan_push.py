#!/usr/bin/env python3
"""Send a ServerChan Turbo notification without exposing its SendKey.

For real WeChat messages use SCT keys only. The SendKey must be supplied
as a GitHub Actions secret and must never be printed or committed.
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class DeliveryError(Exception):
    pass


def send_wechat(sendkey: str, title: str, body: str) -> None:
    if not re.fullmatch(r"SCT[A-Za-z0-9]+", sendkey or ""):
        raise DeliveryError("missing_or_invalid_turbo_sendkey")
    if not title or not body:
        raise DeliveryError("missing_title_or_body")

    endpoint = "https://sctapi.ftqq.com/" + sendkey + ".send"
    encoded = urlencode({"title": title[:120].replace("\n", " "), "desp": body}).encode("utf-8")
    req = Request(endpoint, data=encoded, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "User-Agent": "AltayFareWatch/1.0",
    })
    try:
        with urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                raise DeliveryError("http_non_200")
            raw = resp.read(8192)
            payload = json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        # Do not print exc / .url: the URL contains the secret!
        raise DeliveryError("http_status_" + str(exc.code)) from None
    except URLError:
        raise DeliveryError("push_endpoint_network_error") from None
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise DeliveryError("invalid_server_response") from None
    except TimeoutError:
        raise DeliveryError("push_request_timeout") from None

    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        # Never echo server-provided messages: providers might reflect credentials.
        raise DeliveryError("server_response_not_successful")


if __name__ == "__main__":
    key = os.environ.pop("SERVERCHAN_SENDKEY", "")
    if not key:
        print("ServerChan Turbo GitHub secret is not configured.", file=sys.stderr)
        raise SystemExit(2)
    try:
        send_wechat(
            key,
            "阿勒泰机票通知通道测试",
            "这是一条测试消息，不是真实机票降价。\n\n"
            "GitHub Actions → Server酱Turbo → 微信推送链路正在验证。\n\n"
            "正式监控仅在符合价格条件且未重复提醒时发送消息。",
        )
        print("ServerChan API accepted the test notification. Confirm receipt in WeChat.")
    except DeliveryError as exc:
        print("ServerChan test failed: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
