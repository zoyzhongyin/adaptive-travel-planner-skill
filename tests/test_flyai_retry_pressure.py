"""Offline checks: repeated FlyAI status=1 cannot multiply requests indefinitely."""
import unittest
from scripts.flight_price_watch import effective_leg_attempts

DAY = "2026-12-23"

class RetryPressureTests(unittest.TestCase):
    def test_first_attempts_use_existing_standard_plan(self):
        self.assertEqual(effective_leg_attempts({"max_leg_attempts": 3}, {}, DAY), 3)
        self.assertEqual(effective_leg_attempts({"max_leg_attempts": 3}, {"consecutive_incomplete": {DAY: 2}}, DAY), 3)

    def test_repeated_failures_collapse_to_single_safe_attempt(self):
        for streak in (3,4,5,7,8,9,10,11):
            state={"consecutive_incomplete": {DAY: streak}}
            self.assertEqual(effective_leg_attempts({"max_leg_attempts": 3}, state, DAY), 1)

    def test_periodic_full_plan_can_detect_recovery(self):
        for streak in (6,12):
            self.assertEqual(effective_leg_attempts({"max_leg_attempts": 3},
                {"consecutive_incomplete": {DAY: streak}}, DAY), 3)

    def test_success_reset_restores_full_plan(self):
        self.assertEqual(effective_leg_attempts({"max_leg_attempts": 3},
            {"consecutive_incomplete": {DAY: 0}}, DAY), 3)

    def test_honors_existing_configured_cap(self):
        self.assertEqual(effective_leg_attempts({"max_leg_attempts": 1}, {}, DAY), 1)
        self.assertEqual(effective_leg_attempts({"max_leg_attempts": 2},
            {"consecutive_incomplete": {DAY: 6}}, DAY), 2)
        for invalid in (0,4):
            with self.assertRaises(ValueError):
                effective_leg_attempts({"max_leg_attempts": invalid}, {}, DAY)

if __name__ == "__main__":
    unittest.main()
