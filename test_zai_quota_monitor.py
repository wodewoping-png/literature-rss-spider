# -*- coding: utf-8 -*-

import unittest

from scripts.check_zai_coding_quota import evaluate_quota


class ZAIQuotaMonitorTests(unittest.TestCase):
    def test_current_credit_payload_is_ready_only_near_window_start(self):
        payload = {
            "success": True,
            "data": {
                "limits": [
                    {
                        "type": "CREDIT_LIMIT",
                        "unit": 3,
                        "number": 5,
                        "usage": 2000,
                        "currentValue": 200,
                        "remaining": 1800,
                        "percentage": 99,
                        "nextResetTime": 1786624439633,
                    },
                    {
                        "type": "CREDIT_LIMIT",
                        "unit": 6,
                        "number": 1,
                        "usage": 10000,
                        "currentValue": 2000,
                        "remaining": 8000,
                        "percentage": 20,
                    },
                ]
            },
        }
        decision = evaluate_quota(payload)
        self.assertIsNotNone(decision)
        self.assertTrue(decision.ready)
        self.assertAlmostEqual(decision.session.used_percent, 10.0)
        self.assertEqual(decision.session.label, "5-hour")
        self.assertEqual(decision.weekly.label, "weekly")
        self.assertTrue(decision.session.reset_at.endswith("+00:00"))

    def test_partly_used_session_waits_for_fresh_window(self):
        payload = {
            "data": {
                "limits": [
                    {"type": "TOKENS_LIMIT", "unit": 3, "number": 5, "percentage": 40},
                    {"type": "TOKENS_LIMIT", "unit": 6, "number": 1, "percentage": 30},
                ]
            }
        }
        decision = evaluate_quota(payload)
        self.assertFalse(decision.ready)
        self.assertIn("fresh", decision.reason)

    def test_exhausted_weekly_window_blocks_retry(self):
        payload = [
            {"type": "CREDIT_LIMIT", "unit": 3, "number": 5, "percentage": 0},
            {"type": "CREDIT_LIMIT", "unit": 6, "number": 1, "remaining": 0, "percentage": 100},
        ]
        decision = evaluate_quota(payload)
        self.assertFalse(decision.ready)
        self.assertIn("weekly", decision.reason)

    def test_mcp_only_or_unknown_payload_is_inconclusive(self):
        self.assertIsNone(evaluate_quota({"data": {"limits": [{"type": "TIME_LIMIT", "percentage": 0}]}}))
        self.assertIsNone(evaluate_quota({"data": {"limits": []}}))


if __name__ == "__main__":
    unittest.main()
