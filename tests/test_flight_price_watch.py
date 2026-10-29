"""Alert text, dedupe, and incomplete round trips. No live FlyAI or WeChat calls."""
import json
import os
from datetime import date, datetime, timedelta, timezone
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


def offer(flight, price, *, direct=True, url="https://example.com/book", day="2026-12-05", airline=None):
    leg = {"flight": flight, "from": "TFU", "to": "AAT"}
    if airline:
        leg["airline"] = airline
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
            "legs": [leg],
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
    def run_live(self, legs, state=None, config=None):
        state = {} if state is None else state
        active = CONFIG if config is None else config
        captured = {}
        calls = []

        def fake_send(_key, title, body):
            captured["title"] = title
            captured["body"] = body

        def fake_query(*args, **kwargs):
            calls.append((args, kwargs))
            return legs.pop(0)

        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            with patch.object(watch, "OUT_DIR", out), \
                 patch.object(watch, "query", side_effect=fake_query), \
                 patch.object(watch, "pause"), \
                 patch.object(watch, "maybe_heartbeat", return_value=False), \
                 patch.object(watch, "send_wechat", side_effect=fake_send), \
                 patch.object(watch, "github_commit_state") as save, \
                 patch.object(watch, "WECHAT_KEY", "SCTTESTKEY"), \
                 patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": "", "GITHUB_OUTPUT": ""}, clear=False):
                alerted = watch.perform(active, state, index=0, live=True)
                written = json.loads((out / "watch-result.json").read_text(encoding="utf-8"))
                summary = (out / "watch-result.md").read_text(encoding="utf-8")
        return alerted, state, captured, written, summary, save, calls

    def test_wechat_lists_dates_flights_prices_time_link_and_unverified_fees(self):
        outbound = offer("9C6685", "600.00", url="https://example.com/out")
        inbound = offer("9C6686", "580.00", url="https://example.com/back", day="2026-12-10")
        alerted, state, captured, written, _summary, save, calls = self.run_live([outbound, inbound])
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
        self.assertIn(watch.DEFAULT_ROSTER, body)
        self.assertIn("1 成人，经济舱", body)
        self.assertNotIn("复诊", body)
        self.assertEqual(calls[0][1]["seat_class_name"], "经济舱")
        self.assertEqual(calls[1][1]["seat_class_name"], "经济舱")
        self.assertEqual(written["party"]["adults"], 1)
        self.assertEqual(written["party"]["adults_cli_supported"], False)
        self.assertIn("理想价", captured["title"])
        self.assertEqual(written["taxes_verified"], False)
        self.assertEqual(state["alerts"]["2026-12-05_2026-12-10"]["best_alert_cny"], "1180.00")
        self.assertEqual(save.call_count, 1)

    def test_same_price_does_not_alert_again_until_drop_or_ideal_band(self):
        state = {"alerts": {"2026-12-05_2026-12-10": {"best_alert_cny": "1400"}}}
        outbound = offer("9C6685", "700.00")
        inbound = offer("9C6686", "700.00", day="2026-12-10")
        alerted, _state, captured, _written, _summary, save, _calls = self.run_live([outbound, inbound], state)
        self.assertFalse(alerted)
        self.assertEqual(captured, {})
        self.assertEqual(save.call_count, 0)

        state = {"alerts": {"2026-12-05_2026-12-10": {"best_alert_cny": "1400"}}}
        outbound = offer("9C6685", "650.00")
        inbound = offer("9C6686", "700.00", day="2026-12-10")
        alerted, new_state, captured, _written, _summary, _save, _calls = self.run_live([outbound, inbound], state)
        self.assertTrue(alerted)
        self.assertIn("1350.00", captured["body"])
        self.assertEqual(new_state["alerts"]["2026-12-05_2026-12-10"]["best_alert_cny"], "1350.00")

    def test_missing_return_is_a_data_gap(self):
        alerted, _state, captured, written, summary, save, _calls = self.run_live([
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
        alerted, _state, _captured, written, summary, _save, _calls = self.run_live([
            connecting,
            offer("9C6686", "909.00", day="2026-12-10"),
        ])
        self.assertFalse(alerted)
        self.assertTrue(written["data_gap"])
        self.assertNotIn("1449", summary)
        self.assertNotIn("540.00", json.dumps(written.get("reference_sum_cny")))


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = [
    {"id": "dec08", "anchor": "2026-12-08", "start": "2026-12-08", "end": "2026-12-13"},
    {"id": "dec17", "anchor": "2026-12-17", "start": "2026-12-17", "end": "2026-12-22"},
    {"id": "dec26", "anchor": "2026-12-26", "start": "2026-12-26", "end": "2026-12-31"},
]


def window_config():
    config = {
        "enabled": True,
        "origin": "TFU",
        "destination": "AAT",
        "direct_only": True,
        "adults": 1,
        "cabin": "economy",
        "departure_anchors": ["2026-12-08", "2026-12-17", "2026-12-26"],
        "date_flex_days": 1,
        "stay_nights": 5,
        "rest_windows": WINDOWS,
        "alert_price_cny": 1500,
        "ideal_price_cny": 1200,
        "min_drop_cny": 50,
        "stop_after": "2026-12-31",
        "roster_notice": watch.DEFAULT_ROSTER,
        "calendar_conflicts": [
            {"date": "2026-12-27", "all_day": True, "title": "复诊评估｜信必可是否停药"},
        ],
    }
    config["departure_dates"] = watch.expand_departure_dates(config)
    return config


def priced(dep, total, out_flight, out_airline, back_flight, back_airline, out_price, back_price):
    return_day = date.fromisoformat(dep) + timedelta(days=5)
    return {
        "status": "priced_reference",
        "reference_total_cny": str(total),
        "return_date": return_day.isoformat(),
        "checked_at_bjt": "2026-10-27T12:00:00+08:00",
        "outbound_flight": out_flight,
        "outbound_airline": out_airline,
        "outbound_price_cny": str(out_price),
        "outbound_url": "https://example.com/" + out_flight,
        "return_flight": back_flight,
        "return_airline": back_airline,
        "return_price_cny": str(back_price),
        "return_url": "https://example.com/" + back_flight,
    }


class DateExpansionTests(unittest.TestCase):
    def test_in_window_flex_keeps_anchors_and_plus_one_only(self):
        config = window_config()
        dates = watch.expand_departure_dates(config)
        self.assertEqual(dates, [
            "2026-12-08", "2026-12-09",
            "2026-12-17", "2026-12-18",
            "2026-12-26", "2026-12-27",
        ])
        for retired in ("2026-12-05", "2026-12-07", "2026-12-14", "2026-12-16", "2026-12-23", "2026-12-25"):
            self.assertNotIn(retired, dates)
        self.assertLessEqual(len(dates), 7)
        self.assertEqual(watch.monitored_departure_dates(config), dates)

    def test_explicit_list_must_match_expansion(self):
        config = window_config()
        config["departure_dates"] = ["2026-12-05", "2026-12-14", "2026-12-23"]
        with self.assertRaises(ValueError):
            watch.monitored_departure_dates(config)

    def test_pair_cap_keeps_every_anchor(self):
        config = {
            "departure_anchors": ["2026-12-08", "2026-12-17", "2026-12-26"],
            "date_flex_days": 1,
            "stay_nights": 5,
            "rest_windows": [
                {"id": "wide", "anchor": anchor, "start": "2026-12-01", "end": "2027-01-05"}
                for anchor in ("2026-12-08", "2026-12-17", "2026-12-26")
            ],
        }
        dates = watch.expand_departure_dates(config)
        self.assertEqual(len(dates), 7)
        for anchor in config["departure_anchors"]:
            self.assertIn(anchor, dates)
        self.assertNotIn("2026-12-25", dates)
        self.assertNotIn("2026-12-27", dates)

    def test_live_config_and_state_use_the_new_windows(self):
        raw = (ROOT / "flight-watch/config.json").read_text(encoding="utf-8")
        config = json.loads(raw)
        self.assertEqual(config["origin"], "TFU")
        self.assertEqual(config["destination"], "AAT")
        self.assertEqual(config["destination_label"], "阿勒泰将军山（仅 AAT）")
        self.assertTrue(config["direct_only"])
        self.assertEqual(config["adults"], 1)
        self.assertEqual(config["cabin"], "economy")
        self.assertEqual(config["stay_nights"], 5)
        self.assertEqual(config["date_flex_days"], 1)
        self.assertEqual(config["alert_price_cny"], 1500)
        self.assertEqual(config["ideal_price_cny"], 1200)
        self.assertEqual(config["min_drop_cny"], 50)
        self.assertEqual(config["max_pairs_per_run"], 3)
        self.assertEqual(config["stop_after"], "2026-12-31")
        self.assertNotIn("FYN", raw)
        self.assertNotIn("KJI", raw)
        dates = watch.monitored_departure_dates(config)
        self.assertEqual(dates, [
            "2026-12-08", "2026-12-09",
            "2026-12-17", "2026-12-18",
            "2026-12-26", "2026-12-27",
        ])
        state = json.loads((ROOT / "flight-watch/state.json").read_text(encoding="utf-8"))
        for bucket in ("last_scan_bjt", "last_scan_results", "last_valid_quote_bjt",
                       "consecutive_incomplete", "incomplete_since_bjt", "alerts"):
            # Retired *departure keys* must be pruned. Active itineraries may
            # legitimately return on 12-14/12-23, so inspecting serialized
            # values (including return_date) is a false-positive test.
            bucket_keys = (state.get(bucket) or {}).keys()
            for retired in ("2026-12-05", "2026-12-14", "2026-12-23"):
                self.assertFalse(any(str(key) == retired or str(key).startswith(retired + "_")
                                     for key in bucket_keys), (bucket, retired))


class AirlineAndPartyTests(unittest.TestCase):
    def test_cheapest_direct_keeps_non_9c(self):
        outbound = {"offers": [
            {"direct": False, "price_cny_reference": "100.00", "legs": [{"flight": "EU1815", "airline": "成都航"}]},
            {"direct": True, "price_cny_reference": "900.00", "legs": [{"flight": "9C6685", "airline": "春秋"}]},
            {"direct": True, "price_cny_reference": "700.00", "legs": [{"flight": "3U6573", "airline": "四川航空"}]},
        ]}
        inbound = {"offers": [
            {"direct": True, "price_cny_reference": "800.00", "legs": [{"flight": "9C6686", "airline": "春秋"}]},
            {"direct": True, "price_cny_reference": "650.00", "legs": [{"flight": "CA4123", "airline": "中国国航"}]},
        ]}
        price, out, back = watch.best_direct_price(outbound, inbound)
        self.assertEqual(price, Decimal("1350.00"))
        self.assertEqual(out["legs"][0]["flight"], "3U6573")
        self.assertEqual(back["legs"][0]["flight"], "CA4123")

    def test_route_stays_aat_direct_and_party_is_one_adult_economy(self):
        watch.validate_route(CONFIG)
        party = watch.party_settings({"adults": 1, "cabin": "economy"})
        self.assertEqual(party["seat_class_name"], "经济舱")
        self.assertFalse(party["adults_cli_supported"])
        with self.assertRaises(ValueError):
            watch.validate_route({"origin": "TFU", "destination": "FYN", "direct_only": True})
        with self.assertRaises(ValueError):
            watch.validate_route({"origin": "TFU", "destination": "KJI", "direct_only": True})
        with self.assertRaises(ValueError):
            watch.validate_route({"origin": "TFU", "destination": "AAT", "direct_only": False})
        with self.assertRaises(ValueError):
            watch.party_settings({"adults": 2, "cabin": "economy"})
        with self.assertRaises(ValueError):
            watch.party_settings({"adults": 1, "cabin": "business"})

    def test_alert_names_airline_and_calendar_conflict(self):
        config = dict(CONFIG)
        config["departure_dates"] = ["2026-12-26"]
        config["stop_after"] = "2026-12-31"
        config["calendar_conflicts"] = [
            {"date": "2026-12-27", "all_day": True, "title": "复诊评估｜信必可是否停药"},
        ]
        case = AlertAndGapTests()
        outbound = offer("3U6573", "600.00", url="https://example.com/3u", day="2026-12-26", airline="四川航空")
        inbound = offer("CA4123", "580.00", url="https://example.com/ca", day="2026-12-31", airline="中国国航")
        _alerted, _state, captured, written, summary, _save, calls = case.run_live(
            [outbound, inbound], config=config,
        )
        body = captured["body"]
        self.assertIn("四川航空 3U6573", body)
        self.assertIn("中国国航 CA4123", body)
        self.assertIn(watch.DEFAULT_ROSTER, body)
        self.assertIn("日历冲突：2026-12-27", body)
        self.assertIn("复诊评估｜信必可是否停药", body)
        self.assertIn("四川航空 3U6573", summary)
        self.assertEqual(written["outbound"]["airline"], "四川航空")
        self.assertEqual(calls[0][1]["seat_class_name"], "经济舱")
        joined = " ".join(str(part) for part in calls[0][0])
        self.assertNotIn("adults", joined)


class WindowAlertTests(unittest.TestCase):
    def test_one_lowest_combo_per_window_and_calendar_note(self):
        config = window_config()
        state = {"last_scan_results": {
            "2026-12-08": priced("2026-12-08", "1400.00", "9C6685", "春秋", "9C6686", "春秋", "700.00", "700.00"),
            "2026-12-09": priced("2026-12-09", "1280.00", "3U6573", "四川航空", "CA4123", "中国国航", "640.00", "640.00"),
            "2026-12-26": priced("2026-12-26", "1190.00", "3U8601", "四川航空", "CA8602", "中国国航", "590.00", "600.00"),
        }}
        captured = []

        def fake_send(_key, title, body):
            captured.append((title, body))

        now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone(timedelta(hours=8)))
        with patch.object(watch, "send_wechat", side_effect=fake_send), \
             patch.object(watch, "WECHAT_KEY", "SCTTESTKEY"):
            fallback = watch.notify_window_winners(
                config, state, {"2026-12-08", "2026-12-09", "2026-12-26"}, now,
            )
        self.assertFalse(fallback)
        self.assertEqual(len(captured), 2)
        bodies = "\n".join(body for _title, body in captured)
        self.assertIn("四川航空 3U6573", bodies)
        self.assertIn("中国国航 CA4123", bodies)
        self.assertNotIn("9C6685", bodies)
        self.assertIn("https://example.com/3U6573", bodies)
        self.assertIn(watch.DEFAULT_ROSTER, bodies)
        self.assertEqual(bodies.count("复诊评估｜信必可是否停药"), 1)
        self.assertIn("2026-12-26", bodies)
        digest = watch.format_window_digest(config, state)
        self.assertEqual(digest.count("合计"), 2)
        self.assertIn("尚无完整直飞往返参考价", digest)
        self.assertIn("3U6573", digest)
        self.assertNotIn("9C6685", digest)
        self.assertEqual(digest.count("复诊评估"), 1)

    def test_near_duplicate_inside_fifty_cny_does_not_alert_again(self):
        config = window_config()
        state = {
            "window_alerts": {"dec08": {"best_alert_cny": "1400", "departure": "2026-12-08"}},
            "last_scan_results": {
                "2026-12-09": priced("2026-12-09", "1380.00", "3U6573", "四川航空", "CA4123", "中国国航", "690.00", "690.00"),
            },
        }
        with patch.object(watch, "send_wechat") as send, \
             patch.object(watch, "WECHAT_KEY", "SCTTESTKEY"):
            now = datetime(2026, 10, 27, 13, 0, tzinfo=timezone(timedelta(hours=8)))
            fallback = watch.notify_window_winners(config, state, {"2026-12-09"}, now)
        self.assertFalse(fallback)
        self.assertEqual(send.call_count, 0)

    def test_prune_drops_retired_departure_keys(self):
        state = {
            "last_scan_bjt": {"2026-12-05": "old", "2026-12-08": "keep"},
            "last_scan_results": {"2026-12-14": {}, "2026-12-17": {"status": "priced_reference"}},
            "last_valid_quote_bjt": {"2026-12-23": "old"},
            "consecutive_incomplete": {"2026-12-23": 5, "2026-12-08": 0},
            "incomplete_since_bjt": {"2026-12-23": "old"},
            "alerts": {"2026-12-05_2026-12-10": {"best_alert_cny": "1400"}},
            "window_alerts": {"old": {"departure": "2026-12-14", "best_alert_cny": "1"}},
        }
        removed = watch.prune_retired_itineraries(state, ["2026-12-08", "2026-12-17"])
        self.assertIn("last_scan_bjt:2026-12-05", removed)
        self.assertEqual(set(state["last_scan_bjt"]), {"2026-12-08"})
        self.assertEqual(set(state["last_scan_results"]), {"2026-12-17"})
        self.assertEqual(state["last_valid_quote_bjt"], {})
        self.assertEqual(state["consecutive_incomplete"], {"2026-12-08": 0})
        self.assertEqual(state["incomplete_since_bjt"], {})
        self.assertEqual(state["alerts"], {})
        self.assertEqual(state["window_alerts"], {})


if __name__ == "__main__":
    unittest.main()
