package com.familyfinance.app.model;

import org.json.JSONObject;

public final class BudgetMonth {
    public final int id;
    public final int householdId;
    public final String month;
    public final int includedAccountBalanceCents;
    public final int lowCushionDailyCents;
    public final boolean active;

    public BudgetMonth(
            int id,
            int householdId,
            String month,
            int includedAccountBalanceCents,
            int lowCushionDailyCents,
            boolean active
    ) {
        this.id = id;
        this.householdId = householdId;
        this.month = month;
        this.includedAccountBalanceCents = includedAccountBalanceCents;
        this.lowCushionDailyCents = lowCushionDailyCents;
        this.active = active;
    }

    public static BudgetMonth fromJson(JSONObject json) {
        return new BudgetMonth(
                json.optInt("id"),
                json.optInt("household_id"),
                json.optString("month"),
                json.optInt("included_account_balance_cents"),
                json.optInt("low_cushion_daily_cents"),
                json.optBoolean("is_active")
        );
    }
}
