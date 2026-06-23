package com.familyfinance.app.model;

import org.json.JSONObject;

public final class SafeToSpendResult {
    public final String warningLevel;
    public final String categoryName;
    public final int categoryRemainingBeforeCents;
    public final int categoryRemainingAfterCents;
    public final int cashAfterBillsBeforePurchaseCents;
    public final int cashAfterPurchaseAndBillsCents;
    public final int daysUntilPayday;
    public final boolean lowCushion;
    public final boolean budgetLineFits;
    public final String requiredPhrase;

    public SafeToSpendResult(
            String warningLevel,
            String categoryName,
            int categoryRemainingBeforeCents,
            int categoryRemainingAfterCents,
            int cashAfterBillsBeforePurchaseCents,
            int cashAfterPurchaseAndBillsCents,
            int daysUntilPayday,
            boolean lowCushion,
            boolean budgetLineFits,
            String requiredPhrase
    ) {
        this.warningLevel = warningLevel;
        this.categoryName = categoryName;
        this.categoryRemainingBeforeCents = categoryRemainingBeforeCents;
        this.categoryRemainingAfterCents = categoryRemainingAfterCents;
        this.cashAfterBillsBeforePurchaseCents = cashAfterBillsBeforePurchaseCents;
        this.cashAfterPurchaseAndBillsCents = cashAfterPurchaseAndBillsCents;
        this.daysUntilPayday = daysUntilPayday;
        this.lowCushion = lowCushion;
        this.budgetLineFits = budgetLineFits;
        this.requiredPhrase = requiredPhrase;
    }

    public static SafeToSpendResult fromJson(JSONObject json) {
        return new SafeToSpendResult(
                json.optString("warning_level", ""),
                json.optString("category_name", ""),
                json.optInt("category_remaining_before_cents"),
                json.optInt("category_remaining_after_cents"),
                json.optInt("cash_after_bills_before_purchase_cents"),
                json.optInt("cash_after_purchase_and_bills_cents"),
                json.optInt("days_until_payday"),
                json.optBoolean("low_cushion"),
                json.optBoolean("budget_line_fits"),
                json.optString("required_phrase", "")
        );
    }
}
