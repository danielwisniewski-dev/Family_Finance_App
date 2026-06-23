package com.familyfinance.app.model;

import org.json.JSONObject;

public final class TransactionAssignment {
    public final int id;
    public final int transactionId;
    public final int categoryId;
    public final int amountCents;
    public final String source;
    public final boolean active;

    public TransactionAssignment(
            int id,
            int transactionId,
            int categoryId,
            int amountCents,
            String source,
            boolean active
    ) {
        this.id = id;
        this.transactionId = transactionId;
        this.categoryId = categoryId;
        this.amountCents = amountCents;
        this.source = source;
        this.active = active;
    }

    public static TransactionAssignment fromJson(JSONObject json) {
        return new TransactionAssignment(
                json.optInt("id"),
                json.optInt("transaction_id"),
                json.optInt("category_id"),
                json.optInt("amount_cents"),
                json.optString("source", ""),
                json.optBoolean("active")
        );
    }
}
