package com.familyfinance.app.model;

import org.json.JSONObject;

public final class BudgetCategory {
    public final int id;
    public final String name;
    public final int plannedCents;
    public final int spentCents;
    public final int remainingCents;
    public final boolean archived;

    public BudgetCategory(
            int id,
            String name,
            int plannedCents,
            int spentCents,
            int remainingCents,
            boolean archived
    ) {
        this.id = id;
        this.name = name;
        this.plannedCents = plannedCents;
        this.spentCents = spentCents;
        this.remainingCents = remainingCents;
        this.archived = archived;
    }

    public static BudgetCategory fromJson(JSONObject json) {
        return new BudgetCategory(
                json.optInt("id"),
                json.optString("name", "Unnamed category"),
                json.optInt("planned_cents"),
                json.optInt("spent_cents"),
                json.optInt("remaining_cents"),
                json.optBoolean("archived")
        );
    }

    public boolean isOverspent() {
        return remainingCents < 0;
    }
}
