package com.familyfinance.app.model;

import org.json.JSONObject;

public final class CashAccount {
    public final int id;
    public final String name;
    public final String accountType;
    public final int balanceCents;
    public final int plaidItemId;
    public final boolean includedInCashReality;
    public final String mask;
    public final String officialName;
    public final String subtype;
    public final Integer availableBalanceCents;
    public final Integer currentBalanceCents;

    public CashAccount(
            int id,
            String name,
            String accountType,
            int balanceCents,
            int plaidItemId,
            boolean includedInCashReality,
            String mask,
            String officialName,
            String subtype,
            Integer availableBalanceCents,
            Integer currentBalanceCents
    ) {
        this.id = id;
        this.name = name;
        this.accountType = accountType;
        this.balanceCents = balanceCents;
        this.plaidItemId = plaidItemId;
        this.includedInCashReality = includedInCashReality;
        this.mask = mask;
        this.officialName = officialName;
        this.subtype = subtype;
        this.availableBalanceCents = availableBalanceCents;
        this.currentBalanceCents = currentBalanceCents;
    }

    public static CashAccount fromJson(JSONObject json) {
        return new CashAccount(
                json.optInt("id"),
                json.optString("name", "Account"),
                json.optString("account_type", ""),
                json.optInt("balance_cents"),
                json.optInt("plaid_item_id", 0),
                json.optBoolean("included_in_cash_reality"),
                json.optString("mask", ""),
                json.optString("official_name", ""),
                json.optString("subtype", ""),
                json.has("available_balance_cents") && !json.isNull("available_balance_cents")
                        ? json.optInt("available_balance_cents")
                        : null,
                json.has("current_balance_cents") && !json.isNull("current_balance_cents")
                        ? json.optInt("current_balance_cents")
                        : null
        );
    }
}
