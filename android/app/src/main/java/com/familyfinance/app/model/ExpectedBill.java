package com.familyfinance.app.model;

import org.json.JSONObject;

public final class ExpectedBill {
    public final int id;
    public final String name;
    public final int amountCents;
    public final String dueOn;
    public final boolean paid;

    public ExpectedBill(int id, String name, int amountCents, String dueOn, boolean paid) {
        this.id = id;
        this.name = name;
        this.amountCents = amountCents;
        this.dueOn = dueOn;
        this.paid = paid;
    }

    public static ExpectedBill fromJson(JSONObject json) {
        return new ExpectedBill(
                json.optInt("id"),
                json.optString("name"),
                json.optInt("amount_cents"),
                json.optString("due_on"),
                json.optBoolean("paid")
        );
    }
}
