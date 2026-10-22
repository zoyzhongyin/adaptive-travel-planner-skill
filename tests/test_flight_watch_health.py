"""Verify live batch health and explicit cooldown bypass without network access."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import flight_watch_batch as batch


class BatchHealthTests(unittest.TestCase):
    def run_batch(self, outcome, force=False):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            config = {"enabled": True, "stop_after": "2099-01-01", "departure_dates": ["2098-12-01"]}
            state = {"last_scan_bjt": {"2098-12-01": "2098-01-01T00:00:00+08:00"}}

            def perform(*args, **kwargs):
                if outcome:
                    (out / 'watch-result.json').write_text(json.dumps(outcome))
                return False

            with patch.dict(os.environ, {"FORCE_SCAN": "true" if force else "false", "GITHUB_STEP_SUMMARY": "", "GITHUB_OUTPUT": ""}), \
                 patch.object(batch.watch, 'json_read', side_effect=[config, state]), \
                 patch.object(batch.watch, 'OUT_DIR', out), \
                 patch.object(batch.watch, 'perform', side_effect=perform), \
                 patch.object(batch.watch, 'github_commit_state') as save, \
                 patch.object(batch, 'select_due_dates', return_value=[(0, '2098-12-01')]) as select, \
                 contextlib.redirect_stdout(io.StringIO()):
                batch.main()
            return json.loads((out / 'watch-batch.json').read_text()), select.call_args.args[1], save.call_count

    def test_incomplete_quotes_are_explicitly_degraded(self):
        report, _, _ = self.run_batch({"status": "incomplete_no_reliable_roundtrip_price", "outbound_status": 1})
        self.assertEqual(report['health'], 'degraded')
        self.assertEqual(report['incomplete'], 1)

    def test_complete_quotes_are_healthy(self):
        report, _, _ = self.run_batch({"status": "priced_reference", "reference_sum_cny": "1800"})
        self.assertEqual(report['health'], 'ok')

    def test_force_scan_bypasses_selection_state_only(self):
        _, selected_state, save_count = self.run_batch({"status": "priced_reference"}, force=True)
        self.assertEqual(selected_state, {})
        self.assertEqual(save_count, 1)
        _, selected_state, _ = self.run_batch({"status": "priced_reference"})
        self.assertIn('last_scan_bjt', selected_state)

    def test_missing_output_fails_batch(self):
        with self.assertRaisesRegex(RuntimeError, 'All due itinerary checks failed'):
            self.run_batch(None)
