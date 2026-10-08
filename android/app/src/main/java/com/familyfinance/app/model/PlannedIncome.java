package com.familyfinance.app.model;

import org.json.JSONObject;

public final class PlannedIncome {
    public final int id;
    public final String name;
    public final String kind;
    public final int plannedCents;
    public final int receivedCents;
    public int linkedReceivedCents;

    public PlannedIncome(int id, String name, String kind, int plannedCents, int receivedCents) {
        this.id = id;
        this.name = name;
        this.kind = kind;
        this.plannedCents = plannedCents;
        this.receivedCents = receivedCents;
    }

    public static PlannedIncome fromJson(JSONObject json) {
        PlannedIncome income = new PlannedIncome(
                json.optInt("id"),
                json.optString("name"),
                json.optString("kind", "main"),
                JsonMoney.cents(json, "planned_cents"),
                JsonMoney.cents(json, "received_cents")
        );
        income.linkedReceivedCents = json.has("linked_received_cents") ? JsonMoney.cents(json, "linked_received_cents") : 0;
        return income;
    }
}
