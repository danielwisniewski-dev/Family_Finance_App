package com.familyfinance.app.model;

import org.json.JSONObject;

public final class TransactionLine {
    public final int id;
    public final int amountCents;
    public final String occurredOn;
    public final String name;
    public final String merchantName;
    public final boolean pending;
    public final String categoryHint;
    public final boolean reviewed;
    public final boolean ignored;
    public final String ignoredReason;
    public final String accountName;

    public TransactionLine(
            int id,
            int amountCents,
            String occurredOn,
            String name,
            String merchantName,
            boolean pending,
            String categoryHint,
            boolean reviewed,
            boolean ignored,
            String ignoredReason,
            String accountName
    ) {
        this.id = id;
        this.amountCents = amountCents;
        this.occurredOn = occurredOn;
        this.name = name;
        this.merchantName = merchantName;
        this.pending = pending;
        this.categoryHint = categoryHint;
        this.reviewed = reviewed;
        this.ignored = ignored;
        this.ignoredReason = ignoredReason;
        this.accountName = accountName;
    }

    public static TransactionLine fromJson(JSONObject json) {
        return new TransactionLine(
                json.optInt("id"),
                json.optInt("amount_cents"),
                json.optString("occurred_on", ""),
                json.optString("name", "Transaction"),
                json.optString("merchant_name", ""),
                json.optBoolean("pending"),
                json.optString("category_hint", ""),
                json.optBoolean("reviewed"),
                json.optBoolean("ignored"),
                json.optString("ignored_reason", ""),
                json.optString("account_name", "")
        );
    }

    public String displayName() {
        return merchantName == null || merchantName.isEmpty() ? name : merchantName;
    }
}
