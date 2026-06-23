package com.familyfinance.app.model;

import org.json.JSONObject;

public final class CashAccount {
    public final int id;
    public final String name;
    public final String accountType;
    public final int balanceCents;
    public final boolean includedInCashReality;
    public final String mask;
    public final String officialName;
    public final String subtype;

    public CashAccount(
            int id,
            String name,
            String accountType,
            int balanceCents,
            boolean includedInCashReality,
            String mask,
            String officialName,
            String subtype
    ) {
        this.id = id;
        this.name = name;
        this.accountType = accountType;
        this.balanceCents = balanceCents;
        this.includedInCashReality = includedInCashReality;
        this.mask = mask;
        this.officialName = officialName;
        this.subtype = subtype;
    }

    public static CashAccount fromJson(JSONObject json) {
        return new CashAccount(
                json.optInt("id"),
                json.optString("name", "Account"),
                json.optString("account_type", ""),
                json.optInt("balance_cents"),
                json.optBoolean("included_in_cash_reality"),
                json.optString("mask", ""),
                json.optString("official_name", ""),
                json.optString("subtype", "")
        );
    }
}
