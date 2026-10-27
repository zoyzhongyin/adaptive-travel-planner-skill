"""Parse recorded FlyAI payloads and retry transient status=1 responses offline."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from scripts import flight_fare_query as fare

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DAY = dt.date(2026, 12, 5)


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class RecordedPayloadTests(unittest.TestCase):
    def test_status1_has_no_offers_and_is_not_ready(self):
        parsed = fare.interpret_response(load("flyai_status1.json"), "TFU", "AAT", DAY)
        self.assertEqual(parsed["api_status"], 1)
        self.assertEqual(parsed["api_message"], "搜索机票低价行业失败")
        self.assertEqual(parsed["offers"], [])
        self.assertFalse(fare.leg_ready(parsed, direct_only=True))
        self.assertNotIn("无航班", json.dumps(parsed, ensure_ascii=False))

    def test_recorded_direct_beats_cheaper_connection(self):
        parsed = fare.interpret_response(load("flyai_direct_offer.json"), "TFU", "AAT", DAY)
        self.assertEqual(parsed["raw_offer_count"], 2)
        directs = [item for item in parsed["offers"] if item["direct"]]
        self.assertEqual(len(directs), 1)
        self.assertEqual(directs[0]["legs"][0]["flight"], "9C6685")
        self.assertEqual(directs[0]["price_cny_reference"], "848.00")
        self.assertFalse(directs[0]["taxes_verified"])
        self.assertFalse(directs[0]["baggage_verified"])
        self.assertEqual(parsed["offers"][0]["price_cny_reference"], "540.00")
        self.assertFalse(parsed["offers"][0]["direct"])

    def test_partial_payload_drops_wrong_airport_date_adult_price_and_stops(self):
        parsed = fare.interpret_response(load("flyai_partial_offers.json"), "TFU", "AAT", dt.date(2026, 12, 14))
        self.assertEqual(parsed["raw_offer_count"], 4)
        self.assertEqual(len(parsed["offers"]), 1)
        only = parsed["offers"][0]
        self.assertEqual(only["price_cny_reference"], "400.00")
        self.assertFalse(only["direct"])
        self.assertFalse(fare.leg_ready(parsed, direct_only=True))
        self.assertTrue(fare.leg_ready(parsed, direct_only=False))


class RetryTests(unittest.TestCase):
    def test_status1_then_direct_stops_after_second_attempt(self):
        calls = []
        pauses = []

        def runner(cmd):
            calls.append(cmd)
            if len(calls) == 1:
                return 0, load("flyai_status1.json"), ""
            return 0, load("flyai_direct_offer.json"), ""

        with tempfile.TemporaryDirectory() as temp:
            fare.OUT_DIR = Path(temp)
            result = fare.query(
                "TFU", "AAT", DAY, "out", direct_only=True,
                runner=runner, sleeper=lambda seconds: pauses.append(seconds),
            )
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][calls[0].index("--sort-type") + 1], "3")
        self.assertEqual(calls[1][calls[1].index("--sort-type") + 1], "8")
        self.assertNotIn("--journey-type", calls[0])
        self.assertEqual(pauses, [2])
        self.assertEqual(result["query_strategy"], "iata_direct_first")
        self.assertEqual([item["api_status"] for item in result["attempts"]], [1, 0])
        self.assertTrue(fare.leg_ready(result, direct_only=True))
        joined = " ".join(" ".join(cmd) for cmd in calls)
        self.assertNotIn("SCT", joined)
        self.assertNotIn("FLYAI_API_KEY", joined)

    def test_ready_direct_is_not_retried(self):
        calls = []

        def runner(cmd):
            calls.append(cmd)
            return 0, load("flyai_direct_offer.json"), ""

        with tempfile.TemporaryDirectory() as temp:
            fare.OUT_DIR = Path(temp)
            fare.query("TFU", "AAT", DAY, "out", direct_only=True, runner=runner, sleeper=lambda _s: None)
        self.assertEqual(len(calls), 1)

    def test_connections_only_retry_for_a_direct_and_then_use_city_name(self):
        calls = []

        def runner(cmd):
            calls.append(cmd)
            if len(calls) < 3:
                # Successful payload whose only direct is filtered by the requested date.
                return 0, load("flyai_partial_offers.json"), ""
            body = json.loads(load("flyai_direct_offer.json"))
            body["data"]["itemList"][1]["journeys"][0]["segments"][0]["depDateTime"] = "2026-12-14 09:50:00"
            return 0, json.dumps(body), ""

        with tempfile.TemporaryDirectory() as temp:
            fare.OUT_DIR = Path(temp)
            result = fare.query(
                "TFU", "AAT", dt.date(2026, 12, 14), "out", direct_only=True,
                runner=runner, sleeper=lambda _s: None,
            )
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[2][calls[2].index("--origin") + 1], "成都")
        self.assertEqual(calls[2][calls[2].index("--destination") + 1], "阿勒泰")
        self.assertIn("--journey-type", calls[2])
        self.assertTrue(any(item["direct"] for item in result["offers"]))

    def test_three_failures_remain_a_data_gap(self):
        def runner(_cmd):
            return 0, load("flyai_status1.json"), ""

        with tempfile.TemporaryDirectory() as temp:
            fare.OUT_DIR = Path(temp)
            result = fare.query("AAT", "TFU", dt.date(2026, 12, 10), "back", direct_only=True,
                                runner=runner, sleeper=lambda _s: None)
        self.assertEqual(len(result["attempts"]), 3)
        self.assertFalse(fare.leg_ready(result, direct_only=True))
        self.assertEqual(result["offers"], [])


if __name__ == "__main__":
    unittest.main()
