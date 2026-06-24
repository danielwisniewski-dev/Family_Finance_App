package com.familyfinance.app.model;

import org.json.JSONObject;

public final class MerchantRule {
    public final int id;
    public final int householdId;
    public final int categoryId;
    public final String merchantMatchText;
    public final int priority;
    public final boolean active;
    public final String categoryName;

    public MerchantRule(
            int id,
            int householdId,
            int categoryId,
            String merchantMatchText,
            int priority,
            boolean active,
            String categoryName
    ) {
        this.id = id;
        this.householdId = householdId;
        this.categoryId = categoryId;
        this.merchantMatchText = merchantMatchText;
        this.priority = priority;
        this.active = active;
        this.categoryName = categoryName;
    }

    public static MerchantRule fromJson(JSONObject json) {
        return new MerchantRule(
                json.optInt("id"),
                json.optInt("household_id"),
                json.optInt("category_id"),
                json.optString("merchant_match_text", ""),
                json.optInt("priority", 100),
                json.optBoolean("active"),
                json.optString("category_name", "")
        );
    }
}
