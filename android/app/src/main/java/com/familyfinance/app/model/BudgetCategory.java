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
        this.id = id;
        this.budgetGroupId = budgetGroupId;
        this.name = name;
        this.plannedCents = plannedCents;
        this.spentCents = spentCents;
        this.remainingCents = remainingCents;
        this.archived = archived;
        this.displayOrder = displayOrder;
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
                json.optInt("planned_cents"),
                json.optInt("spent_cents"),
                json.optInt("remaining_cents"),
                json.optBoolean("archived"),
                json.optInt("display_order")
        );
    }

    public boolean isOverspent() {
        return remainingCents < 0;
    }
}
