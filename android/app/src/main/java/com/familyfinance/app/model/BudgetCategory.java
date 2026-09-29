package com.familyfinance.app.model;

import org.json.JSONObject;

public final class BudgetCategory {
    public final int id;
    public final int budgetGroupId;
    public final String name;
    public final int plannedCents;
    public final int spentCents;
    public final int remainingCents;
    public final boolean archived;
    public final int displayOrder;
    public final Integer reserveFundId;

    public BudgetCategory(
            int id,
            int budgetGroupId,
            String name,
            int plannedCents,
            int spentCents,
            int remainingCents,
            boolean archived,
            int displayOrder
    ) {
        this(id, budgetGroupId, name, plannedCents, spentCents, remainingCents, archived, displayOrder, null);
    }

    private BudgetCategory(int id, int budgetGroupId, String name, int plannedCents,
            int spentCents, int remainingCents, boolean archived, int displayOrder, Integer reserveFundId) {
        this.id = id;
        this.budgetGroupId = budgetGroupId;
        this.name = name;
        this.plannedCents = plannedCents;
        this.spentCents = spentCents;
        this.remainingCents = remainingCents;
        this.archived = archived;
        this.displayOrder = displayOrder;
        this.reserveFundId = reserveFundId;
    }

    public BudgetCategory(
            int id,
            String name,
            int plannedCents,
            int spentCents,
            int remainingCents,
            boolean archived
    ) {
        this(id, 0, name, plannedCents, spentCents, remainingCents, archived, 0);
    }

    public static BudgetCategory fromJson(JSONObject json) {
        return new BudgetCategory(
                json.optInt("id"),
                json.optInt("budget_group_id"),
                json.optString("name", "Unnamed category"),
                JsonMoney.cents(json, "planned_cents"),
                JsonMoney.cents(json, "spent_cents"),
                JsonMoney.cents(json, "remaining_cents"),
                json.optBoolean("archived"),
                json.optInt("display_order"),
                json.isNull("reserve_fund_id") ? null : json.optInt("reserve_fund_id")
        );
    }

    public boolean isOverspent() {
        return remainingCents < 0;
    }
}
