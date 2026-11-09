"""2026-11-08 fare-watch regression. No live FlyAI, GitHub, or ServerChan calls."""
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from scripts import build_fare_dashboard as pub
from scripts import flight_fare_query as fare
from scripts import flight_price_watch as watch
from scripts import flight_watch_batch as batch
from scripts.flight_watch_batch import select_due_dates

ROOT = Path(__file__).resolve().parents[1]
BJT = timezone(timedelta(hours=8))
FIXTURES = Path(__file__).resolve().parent / "fixtures"
DATES = [
    "2026-12-08", "2026-12-09", "2026-12-17",
    "2026-12-18", "2026-12-26", "2026-12-27",
]


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class LayerTests(unittest.TestCase):
    def test_json_parse_http_cli_api_and_empty_stay_distinct(self):
        secret = "SCTTESTKEY123456"
        noisy = "prefix " + secret + " " + ("x" * 400)
        parsed = fare.interpret_response(noisy, "TFU", "AAT", datetime(2026, 12, 18).date())
        self.assertEqual(parsed["failure_layer"], "parse")
        self.assertEqual(parsed["error"], "JSONDecodeError")
        self.assertNotIn(secret, json.dumps(parsed))
        self.assertLessEqual(len(parsed["error_detail"]), fare.DIAG_TEXT_LIMIT)
        self.assertNotIn("无航班", json.dumps(parsed, ensure_ascii=False))

        with tempfile.TemporaryDirectory() as temp:
            fare.OUT_DIR = Path(temp)

            def http_runner(_cmd):
                return 1, "<html>HTTP 502 bad gateway</html>", "status code 502"

            http = fare.query("AAT", "TFU", datetime(2026, 12, 23).date(), "back",
                              direct_only=True, runner=http_runner, sleeper=lambda _s: None)
            self.assertEqual(http["failure_layer"], "http")
            self.assertEqual(http["http_status"], 502)
            self.assertEqual(http["offers"], [])

            def cli_runner(_cmd):
                return 1, "", "connect reset"

            cli = fare.query("AAT", "TFU", datetime(2026, 12, 23).date(), "cli",
                             direct_only=True, max_attempts=1, runner=cli_runner, sleeper=lambda _s: None)
            self.assertEqual(cli["failure_layer"], "cli")
            self.assertEqual(cli["stdout_kind"], "empty")
            self.assertIsNone(cli.get("api_status"))

            api = fare.interpret_response(load("flyai_status1.json"), "TFU", "AAT", datetime(2026, 12, 17).date())
            self.assertEqual(api["failure_layer"], "api")
            self.assertEqual(api["api_status"], 1)
            self.assertEqual(api["offers"], [])

            empty = fare.interpret_response(
                json.dumps({"status": 0, "message": "success", "data": {"itemList": []}}),
                "TFU", "AAT", datetime(2026, 12, 17).date(),
            )
            self.assertEqual(empty["failure_layer"], "empty")
            self.assertEqual(empty["offers"], [])
            self.assertFalse(fare.leg_ready(empty, direct_only=True))

    def test_parse_failure_retries_and_a_partial_one_way_is_not_a_round_trip(self):
        calls = []

        def runner(_cmd):
            calls.append(1)
            return 1, "not-json", ""

        with tempfile.TemporaryDirectory() as temp:
            fare.OUT_DIR = Path(temp)
            missed = fare.query(
                "AAT", "TFU", datetime(2026, 12, 23).date(), "back",
                direct_only=True, runner=runner, sleeper=lambda _s: None,
            )
        self.assertEqual(len(calls), 3)
        self.assertEqual(missed["attempts"][0]["failure_layer"], "parse")
        outbound = fare.interpret_response(load("flyai_direct_offer.json"), "TFU", "AAT", datetime(2026, 12, 5).date())
        self.assertIsNone(watch.best_direct_price(outbound, missed))

    def test_empty_stdout_with_mcp_402_is_usage_limit_and_does_not_retry(self):
        calls = []
        stderr = 'MCP HTTP 402: Body: {"jsonrpc":"2.0","id":"1","error":{"code":-32603,"message":"Total usage limit reached"}}'

        def runner(_cmd):
            calls.append(1)
            return 1, "", stderr

        with tempfile.TemporaryDirectory() as temp:
            fare.OUT_DIR = Path(temp)
            result = fare.query(
                "AAT", "TFU", datetime(2026, 12, 23).date(), "back",
                direct_only=True, runner=runner, sleeper=lambda _s: None,
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["error"], "usage_limit")
        self.assertEqual(result["failure_layer"], "http")
        self.assertEqual(result["http_status"], 402)
        self.assertNotEqual(result["error"], "JSONDecodeError")
        self.assertEqual(result["offers"], [])
        self.assertNotIn("无航班", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("jsonrpc", json.dumps(result))

    def test_empty_stdout_with_trial_429_is_not_a_json_parse_failure(self):
        calls = []
        stderr = 'MCP HTTP 429: Body: {"jsonrpc":"2.0","id":"1","error":{"code":-32603,"message":"Trial limit reached. Please visit the console at flyai.open.fliggy.com to get a formal API Key"}}'

        def runner(_cmd):
            calls.append(1)
            return 1, "", stderr

        with tempfile.TemporaryDirectory() as temp:
            fare.OUT_DIR = Path(temp)
            result = fare.query(
                "TFU", "AAT", datetime(2026, 12, 17).date(), "out",
                direct_only=True, seat_class_name="经济舱",
                runner=runner, sleeper=lambda _s: None,
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["error"], "trial_limit")
        self.assertEqual(result["failure_layer"], "http")
        self.assertEqual(result["http_status"], 429)
        self.assertEqual(result["offers"], [])
        self.assertNotIn("flyai.open.fliggy.com", json.dumps(result))

    def test_retry_backoff_is_the_configured_20_then_60_schedule(self):
        config = json.loads((ROOT / "flight-watch/config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["failure_retry_minutes"], 20)
        self.assertEqual(config["each_pair_interval_minutes"], 60)
        state = {
            "last_scan_results": {"2026-12-17": {"status": "incomplete_no_reliable_roundtrip_price"}},
            "consecutive_incomplete": {},
        }
        for streak, expected in ((1, 20), (2, 40), (3, 60), (6, 60)):
            state["consecutive_incomplete"]["2026-12-17"] = streak
            self.assertEqual(batch.pair_interval_minutes(config, state, "2026-12-17"), expected)


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "departure_dates": DATES,
            "each_pair_interval_minutes": 60,
            "failure_retry_minutes": 20,
            "max_pairs_per_run": 3,
        }
        self.scans = {
            "2026-12-08": "2026-11-08T19:52:56+08:00",
            "2026-12-09": "2026-11-08T20:07:54+08:00",
            "2026-12-17": "2026-11-08T19:52:35+08:00",
            "2026-12-18": "2026-11-08T20:07:51+08:00",
            "2026-12-26": "2026-11-08T20:07:39+08:00",
            "2026-12-27": "2026-11-08T19:52:53+08:00",
        }
        self.state = {
            "last_scan_bjt": self.scans,
            "last_scan_results": {day: {"status": "incomplete_no_reliable_roundtrip_price"} for day in DATES},
            "consecutive_incomplete": {
                "2026-12-08": 16, "2026-12-09": 6, "2026-12-17": 26,
                "2026-12-18": 1, "2026-12-26": 14, "2026-12-27": 19,
            },
        }

    def test_2022_slot_skips_and_the_next_slot_is_not_starved(self):
        at_2022 = datetime(2026, 11, 8, 20, 22, tzinfo=BJT)
        self.assertEqual(select_due_dates(self.config, self.state, at_2022), [])
        at_2037 = datetime(2026, 11, 8, 20, 37, tzinfo=BJT)
        self.assertEqual([day for _, day in select_due_dates(self.config, self.state, at_2037)], ["2026-12-18"])

    def test_oldest_overdue_pair_is_selected_ahead_of_recent_failures(self):
        now = datetime(2026, 11, 8, 21, 0, tzinfo=BJT)
        state = {
            "last_scan_bjt": {day: (now - timedelta(minutes=5)).isoformat() for day in DATES},
            "last_scan_results": {day: {"status": "incomplete_no_reliable_roundtrip_price"} for day in DATES},
            "consecutive_incomplete": {day: 4 for day in DATES},
        }
        state["last_scan_bjt"]["2026-12-17"] = (now - timedelta(hours=3)).isoformat()
        picked = [day for _, day in select_due_dates(self.config, state, now)]
        self.assertEqual(picked, ["2026-12-17"])

    def test_december_boundary_keeps_user_dates_until_each_departure_passes(self):
        real = json.loads((ROOT / "flight-watch/config.json").read_text(encoding="utf-8"))
        self.assertEqual(real["departure_dates"], DATES)
        self.assertEqual(real["alert_price_cny"], 1500)
        self.assertEqual(real["ideal_price_cny"], 1200)
        self.assertEqual(real["stop_after"], "2026-12-31")
        self.assertEqual(real["min_drop_cny"], 50)
        dec24 = datetime(2026, 12, 24, 0, 14, tzinfo=BJT)
        self.assertEqual(
            [day for _, day in select_due_dates(real, {}, dec24)],
            ["2026-12-26", "2026-12-27"],
        )
        dec27 = datetime(2026, 12, 27, 23, 44, tzinfo=BJT)
        self.assertEqual([day for _, day in select_due_dates(real, {}, dec27)], ["2026-12-27"])
        dec28 = datetime(2026, 12, 28, 0, 14, tzinfo=BJT)
        self.assertEqual(select_due_dates(real, {}, dec28), [])
        worker = (ROOT / "flight-watch/cloudflare-dispatch/worker.js").read_text(encoding="utf-8")
        self.assertIn('Date.parse("2027-01-01T00:00:00+08:00")', worker)
        workflow = (ROOT / ".github/workflows/altay-fare-watch.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "14,44 * * * *"', workflow)


class DashboardAndAlertTests(unittest.TestCase):
    def test_incomplete_snapshot_keeps_stale_price_out_of_the_current_total(self):
        config = json.loads((ROOT / "flight-watch/config.json").read_text(encoding="utf-8"))
        state = {"last_scan_results": {}, "last_valid_fares": {}}
        for day in DATES:
            state["last_scan_results"][day] = {
                "status": "incomplete_no_reliable_roundtrip_price",
                "checked_at_bjt": "2026-11-08T20:07:51+08:00",
                "return_date": "2026-12-23",
            }
        state["last_scan_results"]["2026-12-18"]["outbound_price_cny"] = "1298.00"
        state["last_valid_fares"]["2026-12-18"] = {
            "checked_at_bjt": "2026-11-08T18:52:48+08:00",
            "reference_total_cny": "2337.00",
        }
        row = next(item for item in pub.snapshot(config, state)["itineraries"] if item["departure"] == "2026-12-18")
        self.assertEqual(row["status"], "incomplete")
        self.assertIsNone(row["total_cny"])
        self.assertIs(row["quote_current"], False)
        self.assertEqual(row["last_success_bjt"], "2026-11-08T18:52:48+08:00")
        self.assertEqual(row["last_failure_bjt"], "2026-11-08T20:07:51+08:00")
        self.assertEqual(row["last_valid"]["total_cny"], "2337.00")
        page = (ROOT / "flight-watch/dashboard/index.html").read_text(encoding="utf-8")
        self.assertIn("陈旧参考价 · 非当前", page)
        self.assertIn("最后成功", page)
        self.assertIn("最近失败", page)
        self.assertIn("工作流显示成功也不等于取得了报价", page)
        self.assertNotIn("historical[0]", page)

    def test_status_change_publishes_inside_the_debounce_window(self):
        previous = {"generated_at_bjt": (datetime.now(BJT) - timedelta(minutes=14)).isoformat(),
                    "most_recent_check_bjt": "2026-11-08T19:52:56+08:00",
                    "itineraries": [{"departure": "2026-12-18", "status": "priced_reference",
                                     "total_cny": "2337.00", "quote_current": True,
                                     "last_valid": {"total_cny": "2337.00"}}]}
        current = {"generated_at_bjt": datetime.now(BJT).isoformat(),
                   "most_recent_check_bjt": "2026-11-08T20:07:51+08:00",
                   "itineraries": [{"departure": "2026-12-18", "status": "incomplete",
                                    "total_cny": None, "quote_current": False,
                                    "last_valid": {"total_cny": "2337.00"}}]}
        self.assertTrue(pub.material_quote_change(previous, current))

        class Response(BytesIO):
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        with patch.object(pub.request, "urlopen", return_value=Response(json.dumps(previous).encode())):
            self.assertTrue(pub.needs_deploy(current))
        same = dict(current, itineraries=previous["itineraries"], most_recent_check_bjt=previous["most_recent_check_bjt"])
        with patch.object(pub.request, "urlopen", return_value=Response(json.dumps(previous).encode())):
            self.assertFalse(pub.needs_deploy(same))

    def test_open_gap_can_remind_after_cooldown_without_sending(self):
        now = datetime(2026, 11, 8, 20, 22, tzinfo=BJT)
        state = {
            "last_anomaly_alert_bjt": "2026-11-07T22:37:52+08:00",
            "last_anomaly_gaps": ["2026-12-17"],
            "anomaly_episode_active": True,
            "incomplete_since_bjt": {"2026-12-17": "2026-11-07T14:07:56+08:00"},
        }
        gaps = batch.monitor_gaps(state, ["2026-12-17"], now)
        self.assertEqual(gaps, ["2026-12-17"])
        self.assertFalse(batch.should_notify_anomaly(state, gaps, now))
        later = datetime(2026, 11, 8, 22, 40, tzinfo=BJT)
        self.assertTrue(batch.should_notify_anomaly(state, gaps, later))
        self.assertFalse(batch.should_notify_anomaly(state, gaps, datetime(2026, 11, 7, 23, 0, tzinfo=BJT)))
        with patch.object(batch.watch, "WECHAT_KEY", "dry-run"), \
             patch.object(batch.watch, "send_wechat") as send, \
             patch("scripts.serverchan_push.urlopen", side_effect=AssertionError("network send")):
            emailed = batch.notify_anomaly(dict(state), gaps, now)
        send.assert_called_once()
        self.assertFalse(emailed)
        body = send.call_args.args[2]
        self.assertNotIn("dry-run", body)
        self.assertNotIn("SCT", body)
        self.assertIn("不能说明没有航班", body)
        recovered = dict(state)
        batch.note_quote_health(recovered, "2026-12-17", "priced_reference", now.isoformat())
        self.assertEqual(batch.monitor_gaps(recovered, ["2026-12-17"], now), [])
        self.assertFalse(batch.should_notify_anomaly(recovered, [], now))


if __name__ == "__main__":
    unittest.main()
