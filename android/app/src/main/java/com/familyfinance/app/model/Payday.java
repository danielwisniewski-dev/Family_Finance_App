package com.familyfinance.app.model;

import org.json.JSONObject;

public final class Payday {
    public final int id;
    public final int householdId;
    public final String paydayDate;

    public Payday(int id, int householdId, String paydayDate) {
        this.id = id;
        this.householdId = householdId;
        this.paydayDate = paydayDate;
    }

    public static Payday fromJson(JSONObject json) {
        return new Payday(
                json.optInt("id"),
                json.optInt("household_id"),
                json.optString("payday_date")
        );
    }
}
