package com.familyfinance.app.model;

import org.json.JSONObject;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;

public final class BudgetSummaryTest {
    @Test
    public void parsesSummaryCategoriesAndAttentionState() throws Exception {
        JSONObject json = new JSONObject(
                "{"
                        + "\"budget_month_id\":1,"
                        + "\"month\":\"2026-06\","
                        + "\"included_account_balance_cents\":100000,"
                        + "\"planned_income_total_cents\":120000,"
                        + "\"assigned_total_cents\":50000,"
                        + "\"remaining_to_assign_cents\":70000,"
                        + "\"total_spent_cents\":52000,"
                        + "\"bills_before_payday_cents\":25000,"
                        + "\"cash_after_bills_cents\":75000,"
                        + "\"days_until_payday\":7,"
                        + "\"next_payday\":\"2026-06-28\","
                        + "\"categories\":["
                        + "{\"id\":10,\"name\":\"Groceries\",\"planned_cents\":50000,\"spent_cents\":52000,\"remaining_cents\":-2000,\"archived\":false}"
                        + "]"
                        + "}"
        );

        BudgetSummary summary = BudgetSummary.fromJson(json);

        assertEquals("2026-06", summary.month);
        assertEquals(1, summary.categories.size());
        assertTrue(summary.categories.get(0).isOverspent());
        assertEquals(1, summary.categoriesNeedingAttention().size());
    }

    private JSONObject budget() throws Exception {
        return new JSONObject("{\"budget_month_id\":1,\"month\":\"2026-09\","
                + "\"included_account_balance_cents\":10000,\"planned_income_total_cents\":20000,"
                + "\"assigned_total_cents\":15000,\"remaining_to_assign_cents\":5000,\"total_spent_cents\":2500,"
                + "\"forecast_available\":true,\"bills_before_payday_cents\":2000,\"cash_after_bills_cents\":8000,"
                + "\"days_until_payday\":10,\"next_payday\":\"2026-09-21\",\"as_of\":\"2026-09-11\",\"categories\":[]}");
    }

    @Test
    public void usesBackendCushionFlagInsteadOfClientThreshold() throws Exception {
        JSONObject json = budget().put("low_cushion", false);
        BudgetSummary summary = BudgetSummary.fromJson(json);
        assertFalse(summary.hasLowCushion()); // $8/day can be above this household's backend threshold.
        assertTrue(BudgetSummary.fromJson(json.put("low_cushion", true)).hasLowCushion());
        assertEquals("2026-09-11", summary.asOf);
    }

    @Test
    public void missingPaydayPreservesPlanAndRepresentsUnknownCashExplicitly() throws Exception {
        JSONObject json = budget().put("forecast_available", false)
                .put("next_payday", JSONObject.NULL).put("days_until_payday", JSONObject.NULL)
                .put("bills_before_payday_cents", JSONObject.NULL).put("cash_after_bills_cents", JSONObject.NULL)
                .put("low_cushion", JSONObject.NULL);
        BudgetSummary summary = BudgetSummary.fromJson(json);
        assertFalse(summary.forecastAvailable);
        assertNull(summary.cashAfterBillsCents);
        assertNull(summary.billsBeforePaydayCents);
        assertNull(summary.daysUntilPayday);
        assertNull(summary.lowCushion);
        assertEquals(10000, summary.includedAccountBalanceCents);
        assertEquals(5000, summary.remainingToAssignCents);
    }
}
