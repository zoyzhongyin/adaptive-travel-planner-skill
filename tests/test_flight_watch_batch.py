"""Test resilient airfare scanning selection without calling FlyAI or WeChat."""
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from scripts import flight_watch_batch as batch
from scripts.flight_watch_batch import (
    anomaly_on_cooldown,
    monitor_gaps,
    note_quote_health,
    select_due_dates,
)

BJT = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 21, 21, 0, tzinfo=BJT)


class ScheduleFairnessTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "departure_dates": ["2026-12-05", "2026-12-14", "2026-12-23"],
            "each_pair_interval_minutes": 90,
            "max_pairs_per_run": 3,
        }

    def test_fresh_monitor_scans_all_pairs(self):
        self.assertEqual([d for _, d in select_due_dates(self.config, {}, NOW)],
                         self.config["departure_dates"])

    def test_delayed_job_catches_up_all_three_pairs(self):
        state = {"last_scan_bjt": {
            day: (NOW - timedelta(hours=5)).isoformat()
            for day in self.config["departure_dates"]
        }}
        self.assertEqual(len(select_due_dates(self.config, state, NOW)), 3)

    def test_recent_pairs_are_not_requeried(self):
        state = {"last_scan_bjt": {
            day: (NOW - timedelta(minutes=15)).isoformat()
            for day in self.config["departure_dates"]
        }}
        self.assertEqual(select_due_dates(self.config, state, NOW), [])

    def test_oldest_pair_first_even_if_time_slots_shift(self):
        days = self.config["departure_dates"]
        state = {"last_scan_bjt": {
            days[0]: (NOW - timedelta(hours=2)).isoformat(),
            days[1]: (NOW - timedelta(hours=4)).isoformat(),
            days[2]: (NOW - timedelta(hours=3)).isoformat(),
        }}
        self.assertEqual([d for _, d in select_due_dates(self.config, state, NOW)],
                         [days[1], days[2], days[0]])

    def test_past_departures_do_not_consume_quota(self):
        config = dict(self.config, departure_dates=["2026-10-01", "2026-12-23"])
        self.assertEqual([d for _, d in select_due_dates(config, {}, NOW)], ["2026-12-23"])

    def test_cap_limits_number_of_api_pairs(self):
        config = dict(self.config, max_pairs_per_run=2)
        self.assertEqual(len(select_due_dates(config, {}, NOW)), 2)

    def _recent_state(self, focus, status, minutes, streak=1):
        recent = (NOW - timedelta(minutes=minutes)).isoformat()
        fresh = (NOW - timedelta(minutes=10)).isoformat()
        last = {}
        results = {}
        streaks = {}
        for day in self.config["departure_dates"]:
            if day == focus:
                last[day] = recent
                results[day] = {"status": status}
                streaks[day] = streak
            else:
                last[day] = fresh
                results[day] = {"status": "priced_reference"}
        return {"last_scan_bjt": last, "last_scan_results": results, "consecutive_incomplete": streaks}

    def test_data_gap_retries_before_the_success_interval(self):
        day = self.config["departure_dates"][0]
        gap_state = self._recent_state(day, "incomplete_no_reliable_roundtrip_price", 25, streak=1)
        self.assertEqual([d for _, d in select_due_dates(self.config, gap_state, NOW)], [day])
        priced = self._recent_state(day, "priced_reference", 25)
        self.assertEqual(select_due_dates(self.config, priced, NOW), [])

    def test_repeated_gaps_back_off_toward_the_success_interval(self):
        day = self.config["departure_dates"][0]
        state = self._recent_state(day, "incomplete_no_reliable_roundtrip_price", 30, streak=3)
        self.assertEqual(select_due_dates(self.config, state, NOW), [])
        state["last_scan_bjt"][day] = (NOW - timedelta(minutes=81)).isoformat()
        self.assertEqual([d for _, d in select_due_dates(self.config, state, NOW)], [day])


class AnomalyTests(unittest.TestCase):
    def test_long_gap_notifies_once_per_cooldown(self):
        now = NOW
        state = {}
        note_quote_health(state, "2026-12-14", "incomplete_no_reliable_roundtrip_price",
                          (now - timedelta(hours=9)).isoformat())
        gaps = monitor_gaps(state, ["2026-12-14"], now)
        self.assertEqual(gaps, ["2026-12-14"])
        self.assertFalse(anomaly_on_cooldown(state, now))
        title, body = batch.build_anomaly_message(gaps, state)
        self.assertIn("监控数据缺口", body)
        self.assertIn("2026-12-14", body)
        self.assertIn("不能说明没有航班", body)
        self.assertIn("不能说明价格高于预算", body)
        self.assertNotIn("SCT", title + body)
        state["last_anomaly_alert_bjt"] = now.isoformat()
        self.assertEqual(monitor_gaps(state, ["2026-12-14"], now), ["2026-12-14"])
        self.assertTrue(anomaly_on_cooldown(state, now))
        self.assertTrue(anomaly_on_cooldown(state, now + timedelta(hours=13)))
        self.assertFalse(anomaly_on_cooldown(state, now + timedelta(hours=25)))

    def test_persistent_outage_is_not_sent_again_after_twenty_four_hours(self):
        state = {"last_anomaly_alert_bjt": NOW.isoformat(),
                 "last_anomaly_gaps": ["2026-12-14"]}
        later = NOW + timedelta(days=2)
        self.assertTrue(batch.anomaly_episode_active(state))
        self.assertFalse(batch.should_notify_anomaly(
            state, ["2026-12-14", "2026-12-23"], later
        ))

    def test_new_outage_after_full_recovery_can_notify_again(self):
        state = {"last_anomaly_alert_bjt": NOW.isoformat(),
                 "last_anomaly_gaps": ["2026-12-14"],
                 "anomaly_episode_active": False}
        self.assertFalse(batch.should_notify_anomaly(
            state, ["2026-12-23"], NOW + timedelta(hours=2)
        ))
        self.assertTrue(batch.should_notify_anomaly(
            state, ["2026-12-23"], NOW + timedelta(hours=25)
        ))

    def test_anomaly_is_initially_sent_only_once_and_text_is_readable(self):
        state = {"incomplete_since_bjt": {
            "2026-12-17": "2026-10-29T12:37:45+08:00",
        }}
        self.assertTrue(batch.should_notify_anomaly(state, ["2026-12-17"], NOW))
        title, message = batch.build_anomaly_message(["2026-12-17"], state)
        self.assertIn("12月17日", message)
        self.assertIn("10月29日 12:37", message)
        self.assertNotIn("2026-10-29T", message)
        self.assertIn("监控异常", title)
        self.assertFalse(batch.should_notify_anomaly(
            {"anomaly_episode_active": True}, ["2026-12-17"], NOW + timedelta(days=3)
        ))

    def test_a_fresh_gap_and_a_recovered_quote_do_not_notify(self):
        now = NOW
        fresh = {}
        note_quote_health(fresh, "2026-12-05", "incomplete_no_reliable_roundtrip_price", now.isoformat())
        self.assertEqual(monitor_gaps(fresh, ["2026-12-05"], now), [])
        recovered = {}
        note_quote_health(recovered, "2026-12-05", "incomplete_no_reliable_roundtrip_price",
                          (now - timedelta(hours=10)).isoformat())
        note_quote_health(recovered, "2026-12-05", "priced_reference", now.isoformat())
        self.assertEqual(monitor_gaps(recovered, ["2026-12-05"], now), [])
        self.assertNotIn("2026-12-05", recovered.get("incomplete_since_bjt", {}))

    def test_select_only_reports_due_without_calling_the_provider(self):
        config = {
            "enabled": True,
            "stop_after": "2099-01-01",
            "departure_dates": ["2098-12-01"],
            "each_pair_interval_minutes": 60,
            "failure_retry_minutes": 20,
            "max_pairs_per_run": 3,
        }
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "github_output"
            with patch.object(batch.watch, "json_read", side_effect=[config, {}]), \
                 patch.object(batch.watch, "perform") as perform, \
                 patch.dict(os.environ, {"GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": "", "FORCE_SCAN": "false"}), \
                 patch.object(batch.sys, "argv", ["flight_watch_batch.py", "--select-only"]):
                batch.main()
            self.assertEqual(perform.call_count, 0)
            text = output.read_text(encoding="utf-8")
            self.assertIn("due=true", text)
            self.assertIn("price_alert=false", text)


if __name__ == "__main__":
    unittest.main()
