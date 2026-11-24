package com.familyfinance.app.model;

import org.json.JSONObject;

public final class ExpectedBill {
    public final int id;
    public final String name;
    public final int amountCents;
    public final String dueOn;
    public final boolean paid;
    public final Integer reserveFundId;
    public final Integer budgetCategoryId;

    public ExpectedBill(int id, String name, int amountCents, String dueOn, boolean paid) {
        this(id, name, amountCents, dueOn, paid, null);
    }

    public ExpectedBill(int id, String name, int amountCents, String dueOn, boolean paid, Integer reserveFundId) {
        this(id, name, amountCents, dueOn, paid, reserveFundId, null);
    }

    public ExpectedBill(int id, String name, int amountCents, String dueOn, boolean paid,
                        Integer reserveFundId, Integer budgetCategoryId) {
        this.id = id;
        this.name = name;
        this.amountCents = amountCents;
        this.dueOn = dueOn;
        this.paid = paid;
        this.reserveFundId = reserveFundId;
        this.budgetCategoryId = budgetCategoryId;
    }

    public static ExpectedBill fromJson(JSONObject json) {
        return new ExpectedBill(
                json.optInt("id"),
                json.optString("name"),
                JsonMoney.cents(json, "amount_cents"),
                json.optString("due_on"),
                json.optBoolean("paid"),
                json.isNull("reserve_fund_id") ? null : json.optInt("reserve_fund_id"),
                json.isNull("budget_category_id") ? null : json.optInt("budget_category_id")
        );
    }
}
