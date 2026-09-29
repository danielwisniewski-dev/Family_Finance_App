"""Keep the documented demo acceptance flow in the normal verification suite."""
import unittest

from backend.smoke_demo import run_smoke


class DemoFeatureSmokeTests(unittest.TestCase):
    def test_normal_features_and_demo_reset_without_real_data_or_provider_access(self):
        result = run_smoke()
        self.assertTrue(result["ok"])
        self.assertEqual(result["outbound_calls"], 0)
        self.assertEqual(result["funded_funds"], 3)
        self.assertEqual(result["reviewed_new_transactions"], 2)
        for area in ("real_database_unchanged", "fresh_reentry", "normal_spending_guards",
                     "fund_contribute_release_move", "budget_edit_copy_manual_spending",
                     "transaction_split_refund_ignore_rules", "coach_advisory_only", "notifications"):
            self.assertTrue(result[area], area)


if __name__ == "__main__":
    unittest.main()
