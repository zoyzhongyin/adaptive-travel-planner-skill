"""2026-11-13: FlyAI paused (HTTP 402 usage_limit); Ctrip public reference is primary.

Locks: thresholds 1500/1200/50 unchanged, repeat-alert rules unchanged for the
Ctrip source, FlyAI never called while paused, and 402/429 quota gaps never
push WeChat anomaly notices. No network, no real pushes.
"""
import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from scripts import build_fare_dashboard as pub
from scripts import ctrip_primary
from scripts import flight_price_watch as watch
from scripts import flight_watch_batch as batch

ROOT = Path(__file__).resolve().parent.parent
BJT = timezone(timedelta(hours=8))
CONFIG = json.loads((ROOT / "flight-watch/config.json").read_text(encoding="utf-8"))


def leg(flight, price, day, hhmm="10:00"):
    return {"flight": flight, "carrier": flight[:2], "airline": "春秋", "cabin": "Y",
            "price_cny": str(price), "base_fare_cny": str(price), "tax_inclusive_cny": None,
            "price_basis": "adult_price_taxes_unverified",
            "departure_time": day + " " + hhmm + ":00", "operating_flight": flight}


def ctrip_snapshot(prices, checked_at, *, config=CONFIG):
    """prices: {departure: (outbound, return)}"""
    items = []
    for dep in config["departure_dates"]:
        ret = (datetime.fromisoformat(dep).date() + timedelta(days=config["stay_nights"])).isoformat()
        if dep not in prices:
            items.append({"departure": dep, "return_date": ret, "checked_at_bjt": checked_at,
                          "status": "incomplete", "total_cny": None, "outbound": None,
                          "return": None, "last_valid": None, "error_types": ["no_valid_listing"]})
            continue
        out, back = prices[dep]
        items.append({"departure": dep, "return_date": ret, "checked_at_bjt": checked_at,
                      "status": "priced_reference", "total_cny": str(Decimal(out) + Decimal(back)),
                      "outbound": leg("9C6685", out, dep), "return": leg("9C6686", back, ret, "15:55"),
                      "last_valid": None, "error_types": []})
    return {"schema_version": 1, "source": "ctrip_browser_public_listing",
            "generated_at_bjt": checked_at, "taxes_verified": False, "cabin_verified": False,
            "baggage_verified": False, "bookability_verified": False, "itineraries": items}


def quota_record(checked_at):
    diag = {"cli_exit": 1, "error": "usage_limit", "http_status": 402,
            "api_message": "Total usage limit reached", "failure_layer": "http"}
    return {"checked_at_bjt": checked_at, "status": "incomplete_no_reliable_roundtrip_price",
            "reference_total_cny": None, "query_diagnostics": {"outbound": diag, "inbound": diag},
            "data_gap": "both_legs", "taxes_verified": False, "baggage_verified": False}


class FixedClock(datetime):
    current = datetime(2026, 11, 13, 9, 0, tzinfo=BJT)

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current


class Harness:
    """Run flight_watch_batch.main() against temp files with every side effect mocked."""

    def __init__(self, testcase, config, state, ctrip):
        self.t = testcase
        self.dir = tempfile.TemporaryDirectory()
        testcase.addCleanup(self.dir.cleanup)
        base = Path(self.dir.name)
        self.config_path, self.state_path, self.ctrip_path = base / "config.json", base / "state.json", base / "ctrip.json"
        self.out_dir = base / "out"
        self.config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        self.state = state
        self.write_ctrip(ctrip)
        self.sent = []

    def write_ctrip(self, ctrip):
        self.ctrip_path.write_text(json.dumps(ctrip, ensure_ascii=False), encoding="utf-8")

    def run(self, now, *, env=None, flyai=None):
        FixedClock.current = now
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        saved = {}

        def commit(state):
            saved["state"] = copy.deepcopy(state)

        def fake_send(key, title, body):
            self.sent.append((title, body))

        environ = {"FORCE_SCAN": "true"}
        environ.update(env or {})
        flyai = flyai or (lambda *a, **k: (_ for _ in ()).throw(AssertionError("FlyAI must not be called")))
        with patch.object(watch, "CONFIG_PATH", self.config_path), \
             patch.object(watch, "STATE_PATH", self.state_path), \
             patch.object(watch, "OUT_DIR", self.out_dir), \
             patch.object(ctrip_primary, "CTRIP_PATH", self.ctrip_path), \
             patch.object(batch, "datetime", FixedClock), \
             patch.object(watch, "github_commit_state", side_effect=commit), \
             patch.object(watch, "WECHAT_KEY", "test-only-not-a-key"), \
             patch.object(watch, "send_wechat", side_effect=fake_send), \
             patch.object(watch, "perform", side_effect=AssertionError("FlyAI perform must not run")), \
             patch.object(batch, "flyai_record", side_effect=flyai), \
             patch("scripts.serverchan_push.urlopen", side_effect=AssertionError("network send")), \
             patch.object(batch.sys, "argv", ["flight_watch_batch.py"]), \
             patch.dict(os.environ, environ, clear=False):
            os.environ.pop("GITHUB_OUTPUT", None)
            os.environ.pop("GITHUB_STEP_SUMMARY", None)
            if "FLYAI_ENABLED" not in environ:
                os.environ.pop("FLYAI_ENABLED", None)
            with redirect_stdout(io.StringIO()) as out:
                batch.main()
        self.state = saved.get("state", self.state)
        return out.getvalue()


def single_window_config():
    """Two departure dates (one rest window) so FORCE_SCAN covers all in one run."""
    config = copy.deepcopy(CONFIG)
    config["departure_anchors"] = ["2026-12-08"]
    config["rest_windows"] = [config["rest_windows"][0]]
    config["departure_dates"] = ["2026-12-08", "2026-12-09"]
    return config


class ThresholdLockTest(unittest.TestCase):
    def test_thresholds_and_repeat_rule_values_unchanged(self):
        self.assertEqual(CONFIG["alert_price_cny"], 1500)
        self.assertEqual(CONFIG["ideal_price_cny"], 1200)
        self.assertEqual(CONFIG["min_drop_cny"], 50)
        self.assertIs(CONFIG["flyai_enabled"], False)
        self.assertEqual(CONFIG["primary_source"], "ctrip_public_reference")

    def test_should_alert_rule_is_unchanged(self):
        alert = lambda price, prior=None: watch.should_alert(Decimal(price), prior, CONFIG)
        self.assertTrue(alert("1499"))
        self.assertTrue(alert("1500"))   # existing rule: at or below the line alerts
        self.assertFalse(alert("1501"))
        self.assertFalse(alert("1499", "1499"))   # same price: no repeat
        self.assertFalse(alert("1450", "1499"))   # 49 drop: no repeat
        self.assertTrue(alert("1449", "1499"))    # >= 50 drop: alert again
        self.assertTrue(alert("1200", "1210"))    # entering ideal zone: alert again
        self.assertFalse(alert("1195", "1200"))   # already ideal, < 50 drop


class SwitchTest(unittest.TestCase):
    def test_config_decides_env_overrides(self):
        self.assertFalse(ctrip_primary.flyai_enabled(CONFIG, {}))
        self.assertTrue(ctrip_primary.flyai_enabled(CONFIG, {"FLYAI_ENABLED": "true"}))
        self.assertFalse(ctrip_primary.flyai_enabled({"flyai_enabled": True}, {"FLYAI_ENABLED": "false"}))
        self.assertTrue(ctrip_primary.flyai_enabled({}, {}))  # legacy default
        self.assertFalse(ctrip_primary.flyai_enabled(CONFIG, {"FLYAI_ENABLED": ""}))

    def test_flyai_code_is_kept(self):
        self.assertTrue(callable(batch.flyai_record))
        self.assertTrue(callable(watch.perform))
        wf = (ROOT / ".github/workflows/altay-fare-watch.yml").read_text(encoding="utf-8")
        self.assertIn("steps.source.outputs.flyai == 'true'", wf)
        self.assertIn("@fly-ai/flyai-cli", wf)

    def test_worker_cutoff_unchanged(self):
        worker = (ROOT / "flight-watch/cloudflare-dispatch/worker.js").read_text(encoding="utf-8")
        self.assertIn('Date.parse("2027-01-01T00:00:00+08:00")', worker)
        toml = (ROOT / "flight-watch/cloudflare-dispatch/wrangler.toml").read_text(encoding="utf-8")
        self.assertIn('crons = ["7,22,37,52 * * * *"]', toml)


class CtripRecordTest(unittest.TestCase):
    now = datetime(2026, 11, 13, 9, 0, tzinfo=BJT)
    stamp = "2026-11-13T04:50:00+08:00"

    def test_valid_itinerary_becomes_priced_reference(self):
        snap = ctrip_snapshot({"2026-12-09": ("660", "780")}, self.stamp)
        rec = ctrip_primary.ctrip_record(CONFIG, snap, "2026-12-09", self.now)
        self.assertEqual(rec["status"], "priced_reference")
        self.assertEqual(rec["reference_total_cny"], "1440.00")
        self.assertEqual(rec["return_date"], "2026-12-14")
        self.assertEqual(rec["data_source"], "ctrip_public_reference")
        self.assertEqual(rec["source_checked_at_bjt"], self.stamp)
        self.assertEqual((rec["outbound_flight"], rec["return_flight"]), ("9C6685", "9C6686"))
        self.assertTrue(rec["outbound_url"].startswith("https://flights.ctrip.com/"))

    def test_real_repository_snapshot_parses(self):
        snap = json.loads((ROOT / "flight-watch/ctrip-latest.json").read_text(encoding="utf-8"))
        when = datetime.fromisoformat(snap["generated_at_bjt"])
        priced = [ctrip_primary.ctrip_record(CONFIG, snap, d, when)["status"] for d in CONFIG["departure_dates"]]
        self.assertTrue(ctrip_primary.snapshot_valid(snap))
        self.assertIn("priced_reference", priced)

    def test_gaps_never_price(self):
        good = ctrip_snapshot({"2026-12-09": ("660", "780")}, self.stamp)
        cases = {
            "stale": (good, self.now + timedelta(hours=19)),
            "future": (ctrip_snapshot({"2026-12-09": ("660", "780")}, "2026-11-13T12:00:00+08:00"), self.now),
            "bad_source": ({**good, "source": "other"}, self.now),
            "taxes_claimed": ({**good, "taxes_verified": True}, self.now),
            "missing": (None, self.now),
        }
        mismatch = copy.deepcopy(good)
        mismatch["itineraries"][1]["total_cny"] = "1300"
        cases["total_mismatch"] = (mismatch, self.now)
        wrong_ret = copy.deepcopy(good)
        wrong_ret["itineraries"][1]["return_date"] = "2026-12-15"
        cases["return_mismatch"] = (wrong_ret, self.now)
        bad_flight = copy.deepcopy(good)
        bad_flight["itineraries"][1]["outbound"]["flight"] = "XX"
        cases["bad_flight"] = (bad_flight, self.now)
        for name, (snap, when) in cases.items():
            with self.subTest(name):
                rec = ctrip_primary.ctrip_record(CONFIG, snap, "2026-12-09", when)
                self.assertEqual(rec["status"], "incomplete_no_reliable_roundtrip_price")
                self.assertIsNone(rec["reference_total_cny"])
                self.assertTrue(rec["data_gap"])


class CtripPrimaryBatchTest(unittest.TestCase):
    def setUp(self):
        self.config = single_window_config()
        self.t0 = datetime(2026, 11, 13, 9, 0, tzinfo=BJT)

    def snap(self, out, back, at):
        return ctrip_snapshot({"2026-12-09": (out, back)}, at.isoformat(timespec="seconds"), config=self.config)

    def test_repeat_alert_rules_with_ctrip_source(self):
        h = Harness(self, self.config, {"version": 1}, self.snap("700", "799", self.t0))
        h.run(self.t0 + timedelta(minutes=5))
        self.assertEqual(len(h.sent), 1, "first 1499 must alert once")
        title, body = h.sent[0]
        self.assertIn("1499", title)
        self.assertIn("携程公开页面参考价", body)
        self.assertIn("2026-11-13 09:00（北京时间）", body)
        rec = h.state["last_scan_results"]["2026-12-09"]
        self.assertEqual(rec["data_source"], "ctrip_public_reference")
        # Same snapshot read again 15 minutes later: no repeat.
        h.run(self.t0 + timedelta(minutes=20))
        self.assertEqual(len(h.sent), 1)
        # 49 drop: no repeat.
        h.write_ctrip(self.snap("700", "750", self.t0 + timedelta(hours=1)))
        h.run(self.t0 + timedelta(hours=1, minutes=5))
        self.assertEqual(len(h.sent), 1)
        # 50 drop from the last alert (1499 -> 1449): alert again.
        h.write_ctrip(self.snap("700", "749", self.t0 + timedelta(hours=2)))
        h.run(self.t0 + timedelta(hours=2, minutes=5))
        self.assertEqual(len(h.sent), 2)
        # Enter the ideal zone with a small drop (1210 alerted earlier -> 1200).
        h.state["window_alerts"]["dec08"]["best_alert_cny"] = "1210"
        h.write_ctrip(self.snap("600", "600", self.t0 + timedelta(hours=3)))
        h.run(self.t0 + timedelta(hours=3, minutes=5))
        self.assertEqual(len(h.sent), 3)
        self.assertIn("理想价", h.sent[-1][0])

    def test_above_alert_line_never_alerts(self):
        h = Harness(self, self.config, {"version": 1}, self.snap("700", "801", self.t0))
        h.run(self.t0 + timedelta(minutes=5))
        self.assertEqual(h.sent, [])
        self.assertEqual(h.state["last_scan_results"]["2026-12-09"]["reference_total_cny"], "1501.00")

    def test_stale_snapshot_is_gap_not_alert(self):
        h = Harness(self, self.config, {"version": 1}, self.snap("600", "500", self.t0 - timedelta(hours=30)))
        h.run(self.t0)
        self.assertEqual(h.sent, [])
        self.assertEqual(h.state["last_scan_results"]["2026-12-09"]["data_gap"], "ctrip_snapshot_stale")

    def test_paused_flyai_after_402_episode_sends_nothing(self):
        stamp = "2026-11-13T07:07:00+08:00"
        state = {"version": 1,
                 "last_scan_results": {d: quota_record(stamp) for d in self.config["departure_dates"]},
                 "incomplete_since_bjt": {d: "2026-11-12T20:00:00+08:00" for d in self.config["departure_dates"]},
                 "consecutive_incomplete": {d: 20 for d in self.config["departure_dates"]},
                 "window_alerts": {"dec08": {"best_alert_cny": "1439.00", "departure": "2026-12-09",
                                             "return": "2026-12-14", "last_alert_at_bjt": "2026-11-13T00:52:48+08:00",
                                             "delivery_channel": "wechat"}}}
        h = Harness(self, self.config, state, self.snap("660", "780", self.t0))
        h.run(self.t0 + timedelta(minutes=5))
        self.assertEqual(h.sent, [], "1440 vs prior 1439 alert and no anomaly push")
        self.assertFalse(h.state["anomaly_episode_active"])
        self.assertEqual(h.state["last_scan_results"]["2026-12-09"]["status"], "priced_reference")


class QuotaSilenceTest(unittest.TestCase):
    def test_repeated_402_never_pushes_anomaly(self):
        config = single_window_config()
        start = datetime(2026, 11, 13, 7, 7, tzinfo=BJT)

        def flyai(cfg, state, index, dep):
            return quota_record(FixedClock.current.isoformat(timespec="seconds"))

        h = Harness(self, config, {"version": 1}, ctrip_snapshot({}, start.isoformat(), config=config))
        outputs = []
        for step in range(0, 72, 3):  # every 3h for 3 days: well past the 8h anomaly line
            outputs.append(h.run(start + timedelta(hours=step), env={"FLYAI_ENABLED": "true"}, flyai=flyai))
        self.assertEqual(h.sent, [], "402/429 quota gaps must not push WeChat anomaly notices")
        self.assertEqual(sorted(h.state["quota_blocked_dates"]), config["departure_dates"])
        self.assertIn("quota_blocked_since_bjt", h.state)
        self.assertNotIn("last_anomaly_alert_bjt", h.state)
        self.assertTrue(any("402/429" in o for o in outputs))

    def test_429_trial_limit_is_quota_too(self):
        rec = quota_record("2026-11-13T07:07:00+08:00")
        rec["query_diagnostics"]["outbound"].update(error="trial_limit", http_status=429)
        rec["query_diagnostics"]["inbound"] = {"error": "JSONDecodeError"}
        self.assertTrue(ctrip_primary.is_quota_record(rec))
        self.assertFalse(ctrip_primary.is_quota_record({"query_diagnostics": {"outbound": {"error": "status_1"}}}))

    def test_non_quota_gap_keeps_existing_once_per_episode_notice(self):
        state = {"last_scan_results": {"2026-12-09": {"status": "incomplete_no_reliable_roundtrip_price",
                                                      "query_diagnostics": {"outbound": {"error": "status_1"}}}}}
        quota, other = ctrip_primary.split_quota_gaps(state, ["2026-12-09"])
        self.assertEqual((quota, other), ([], ["2026-12-09"]))


class PublicSnapshotTest(unittest.TestCase):
    def test_api_fares_names_ctrip_primary_source_and_time(self):
        stamp = "2026-11-13T04:50:06+08:00"
        snap = ctrip_snapshot({"2026-12-09": ("660", "780")}, stamp)
        rec = ctrip_primary.ctrip_record(CONFIG, snap, "2026-12-09", datetime(2026, 11, 13, 9, 0, tzinfo=BJT))
        state = {"last_scan_results": {"2026-12-09": rec}}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FLYAI_ENABLED", None)
            public = pub.snapshot(CONFIG, state, ctrip=snap)
        self.assertIs(public["flyai_enabled"], False)
        self.assertEqual(public["primary_source"], "ctrip_public_reference")
        self.assertEqual(public["primary_source_label"], "携程公开页面参考价")
        self.assertEqual(public["primary_source_checked_at_bjt"], stamp)
        self.assertEqual(public["alert_price_cny"], 1500)
        self.assertEqual(public["ideal_price_cny"], 1200)
        row = next(r for r in public["itineraries"] if r["departure"] == "2026-12-09")
        self.assertEqual((row["status"], row["total_cny"], row["source"], row["source_checked_at_bjt"]),
                         ("priced_reference", "1440.00", "ctrip_public_reference", stamp))
        text = json.dumps(public, ensure_ascii=False)
        for secret_name in ("SENDKEY", "GH_ACTIONS_TOKEN", "query_diagnostics", "test-only"):
            self.assertNotIn(secret_name, text)


if __name__ == "__main__":
    unittest.main()
