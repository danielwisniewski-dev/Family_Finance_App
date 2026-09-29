package com.familyfinance.app.model;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

import static org.junit.Assert.*;

public final class ProvisionFundsTest {
    private JSONObject overview() throws Exception {
        JSONObject fund = new JSONObject().put("id", 7).put("name", "Repairs").put("category_id", 10)
                .put("backing_account_id", 2).put("backing_account_name", "Checking")
                .put("monthly_plan_cents", 10000).put("annual_target_cents", 120000)
                .put("contributed_this_month_cents", 2500).put("spent_this_month_cents", 18000)
                .put("balance_cents", 34200).put("monthly_shortfall_cents", 7500)
                .put("breakdown", new JSONArray().put(new JSONObject().put("name", "Annual service")
                        .put("annual_cents", 30000).put("timing_note", "June")))
                .put("entries", new JSONArray().put(new JSONObject().put("kind", "release")
                        .put("amount_cents", -500).put("occurred_on", "2026-09-20").put("actor_name", "Member")));
        return new JSONObject().put("budget_month_id", 12).put("month", "2026-09")
                .put("total_planned_cents", 10000).put("total_contributed_cents", 2500)
                .put("total_spent_cents", 18000).put("total_balance_cents", 34200)
                .put("total_shortfall_cents", 7500).put("reserved_included_cents", 34200)
                .put("funds", new JSONArray().put(fund));
    }

    @Test
    public void carriesServerBalanceWithoutRecalculatingFromMonthlyPlan() throws Exception {
        ProvisionFunds funds = ProvisionFunds.fromJson(overview());
        assertEquals(34200, funds.totalBalanceCents);
        assertEquals(34200, funds.find(7).balanceCents);
        assertEquals(7500, funds.find(7).monthlyShortfallCents);
        assertEquals(-500, funds.find(7).entries.get(0).amountCents);
        assertEquals("Member", funds.find(7).entries.get(0).actorName);
        assertEquals("June", funds.find(7).breakdown.get(0).timingNote);
    }

    @Test(expected = IllegalArgumentException.class)
    public void absentSavedBalanceIsNeverPresentedAsZero() throws Exception {
        JSONObject json = overview();
        json.getJSONArray("funds").getJSONObject(0).remove("balance_cents");
        ProvisionFunds.fromJson(json);
    }

    @Test
    public void fundWithoutMonthlyCategoryPreservesUnknownLink() throws Exception {
        JSONObject json = overview();
        json.getJSONArray("funds").getJSONObject(0).put("category_id", JSONObject.NULL);
        assertNull(ProvisionFunds.fromJson(json).find(7).categoryId);
    }

    @Test
    public void expectedBillCanPreserveAndClearItsFundLink() throws Exception {
        JSONObject bill = new JSONObject().put("id", 1).put("name", "Annual service")
                .put("amount_cents", 10000).put("due_on", "2026-10-01").put("reserve_fund_id", 7);
        assertEquals(Integer.valueOf(7), ExpectedBill.fromJson(bill).reserveFundId);
        assertNull(ExpectedBill.fromJson(bill.put("reserve_fund_id", JSONObject.NULL)).reserveFundId);
    }
}
