"""Test resilient airfare scanning selection without calling FlyAI or WeChat."""
import unittest
from datetime import datetime, timedelta, timezone
from scripts.flight_watch_batch import select_due_dates

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


if __name__ == "__main__":
    unittest.main()
