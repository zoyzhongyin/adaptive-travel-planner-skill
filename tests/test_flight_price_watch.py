"""Alert text, dedupe, and incomplete round trips. No live FlyAI or WeChat calls."""
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import flight_price_watch as watch

CONFIG = {
    "enabled": True,
    "origin": "TFU",
    "destination": "AAT",
    "departure_dates": ["2026-12-05"],
    "stay_nights": 5,
    "direct_only": True,
    "alert_price_cny": 1500,
    "ideal_price_cny": 1200,
    "min_drop_cny": 50,
    "stop_after": "2026-12-23",
    "max_leg_attempts": 3,
}


def offer(flight, price, *, direct=True, url="https://example.com/book", day="2026-12-05"):
    return {
        "api_status": 0,
        "raw_offer_count": 1,
        "api_message": "success",
        "attempts": [{"label": "iata_price_asc", "api_status": 0}],
        "offers": [{
            "direct": direct,
            "price_cny_reference": str(price),
            "departure": day + " 09:50:00",
            "arrival": day + " 14:05:00",
            "booking_url": url,
            "legs": [{"flight": flight, "from": "TFU", "to": "AAT"}],
        }],
    }


def gap(status=1, message="搜索机票低价行业失败"):
    return {
        "api_status": status,
        "raw_offer_count": 0,
        "api_message": message,
        "offers": [],
        "attempts": [{"label": "iata_price_asc", "api_status": status}, {"label": "iata_direct_first", "api_status": status}],
    }


class DedupeTests(unittest.TestCase):
    def test_threshold_drop_and_ideal_band(self):
        should = watch.should_alert
        self.assertFalse(should(Decimal("1757"), None, CONFIG))
        self.assertTrue(should(Decimal("1490"), None, CONFIG))
        self.assertFalse(should(Decimal("1490"), "1490", CONFIG))
        self.assertFalse(should(Decimal("1470"), "1490", CONFIG))
        self.assertTrue(should(Decimal("1440"), "1490", CONFIG))
        self.assertTrue(should(Decimal("1200"), "1400", CONFIG))
        self.assertFalse(should(Decimal("1200"), "1200", CONFIG))
        self.assertFalse(should(Decimal("1190"), "1200", CONFIG))
        self.assertTrue(should(Decimal("1150"), "1200", CONFIG))


class AlertAndGapTests(unittest.TestCase):
    def run_live(self, legs, state=None):
        state = {} if state is None else state
        captured = {}

        def fake_send(_key, title, body):
            captured["title"] = title
            captured["body"] = body

        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            with patch.object(watch, "OUT_DIR", out), \
                 patch.object(watch, "query", side_effect=legs), \
                 patch.object(watch, "pause"), \
                 patch.object(watch, "maybe_heartbeat", return_value=False), \
                 patch.object(watch, "send_wechat", side_effect=fake_send), \
                 patch.object(watch, "github_commit_state") as save, \
                 patch.object(watch, "WECHAT_KEY", "SCTTESTKEY"), \
                 patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": "", "GITHUB_OUTPUT": ""}, clear=False):
                alerted = watch.perform(CONFIG, state, index=0, live=True)
                written = json.loads((out / "watch-result.json").read_text(encoding="utf-8"))
                summary = (out / "watch-result.md").read_text(encoding="utf-8")
        return alerted, state, captured, written, summary, save

    def test_wechat_lists_dates_flights_prices_time_link_and_unverified_fees(self):
        outbound = offer("9C6685", "600.00", url="https://example.com/out")
        inbound = offer("9C6686", "580.00", url="https://example.com/back", day="2026-12-10")
        alerted, state, captured, written, _summary, save = self.run_live([outbound, inbound])
        self.assertTrue(alerted)
        body = captured["body"]
        self.assertIn("2026-12-05", body)
        self.assertIn("2026-12-10", body)
        self.assertIn("9C6685", body)
        self.assertIn("9C6686", body)
        self.assertIn("直飞", body)
        self.assertIn("600.00", body)
        self.assertIn("580.00", body)
        self.assertIn("1180.00", body)
        self.assertIn("北京时间", body)
        self.assertIn("https://example.com/out", body)
        self.assertIn("https://example.com/back", body)
        self.assertIn("税费、机建燃油：未核实", body)
        self.assertIn("托运行李：未核实", body)
        self.assertIn("雪具运输：未核实", body)
        self.assertIn("理想价", captured["title"])
        self.assertEqual(written["taxes_verified"], False)
        self.assertEqual(state["alerts"]["2026-12-05_2026-12-10"]["best_alert_cny"], "1180.00")
        self.assertEqual(save.call_count, 1)

    def test_same_price_does_not_alert_again_until_drop_or_ideal_band(self):
        state = {"alerts": {"2026-12-05_2026-12-10": {"best_alert_cny": "1400"}}}
        outbound = offer("9C6685", "700.00")
        inbound = offer("9C6686", "700.00", day="2026-12-10")
        alerted, _state, captured, _written, _summary, save = self.run_live([outbound, inbound], state)
        self.assertFalse(alerted)
        self.assertEqual(captured, {})
        self.assertEqual(save.call_count, 0)

        state = {"alerts": {"2026-12-05_2026-12-10": {"best_alert_cny": "1400"}}}
        outbound = offer("9C6685", "650.00")
        inbound = offer("9C6686", "700.00", day="2026-12-10")
        alerted, new_state, captured, _written, _summary, _save = self.run_live([outbound, inbound], state)
        self.assertTrue(alerted)
        self.assertIn("1350.00", captured["body"])
        self.assertEqual(new_state["alerts"]["2026-12-05_2026-12-10"]["best_alert_cny"], "1350.00")

    def test_missing_return_is_a_data_gap(self):
        alerted, _state, captured, written, summary, save = self.run_live([
            offer("9C6685", "848.00"),
            gap(),
        ])
        self.assertFalse(alerted)
        self.assertEqual(captured, {})
        self.assertEqual(written["status"], "incomplete_no_reliable_roundtrip_price")
        self.assertEqual(written["inbound_status"], 1)
        self.assertTrue(written["data_gap"])
        self.assertIsNone(written.get("reference_sum_cny"))
        self.assertEqual(written["outbound"]["flight"], "9C6685")
        self.assertEqual(written["outbound"]["price_cny_reference"], "848.00")
        self.assertNotIn("return", written)
        self.assertIn("往返合计未计算", summary)
        self.assertIn("数据缺口", summary)
        self.assertIn("不能据此判断没有航班", summary)
        self.assertIn("不能据此判断价格高于预算", summary)
        self.assertEqual(save.call_count, 0)

    def test_connection_plus_priced_return_does_not_invent_a_nonstop_total(self):
        connecting = offer("EU1815", "540.00", direct=False)
        alerted, _state, _captured, written, summary, _save = self.run_live([
            connecting,
            offer("9C6686", "909.00", day="2026-12-10"),
        ])
        self.assertFalse(alerted)
        self.assertTrue(written["data_gap"])
        self.assertNotIn("1449", summary)
        self.assertNotIn("540.00", json.dumps(written.get("reference_sum_cny")))


if __name__ == "__main__":
    unittest.main()
