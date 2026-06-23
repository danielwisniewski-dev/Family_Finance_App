package com.familyfinance.app.model;

import org.json.JSONObject;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public final class BudgetSummaryTest {
    @Test
    public void parsesSummaryCategoriesAndAttentionState() throws Exception {
        JSONObject json = new JSONObject(
                "{"
                        + "\"budget_month_id\":1,"
                        + "\"month\":\"2026-06\","
                        + "\"included_account_balance_cents\":100000,"
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
}
