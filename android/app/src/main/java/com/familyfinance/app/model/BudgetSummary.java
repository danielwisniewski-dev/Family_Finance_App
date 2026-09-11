package com.familyfinance.app.model;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class BudgetSummary {
    public final int budgetMonthId;
    public final String month;
    public final int includedAccountBalanceCents;
    public final int plannedIncomeTotalCents;
    public final int assignedTotalCents;
    public final int remainingToAssignCents;
    public final int totalSpentCents;
    public final Integer billsBeforePaydayCents;
    public final Integer cashAfterBillsCents;
    public final Integer daysUntilPayday;
    public final String nextPayday;
    public final boolean forecastAvailable;
    public final Boolean lowCushion;
    public final String asOf;
    public final List<BudgetCategory> categories;

    public BudgetSummary(
            int budgetMonthId,
            String month,
            int includedAccountBalanceCents,
            int plannedIncomeTotalCents,
            int assignedTotalCents,
            int remainingToAssignCents,
            int totalSpentCents,
            int billsBeforePaydayCents,
            int cashAfterBillsCents,
            int daysUntilPayday,
            String nextPayday,
            List<BudgetCategory> categories
    ) {
        this(budgetMonthId, month, includedAccountBalanceCents, plannedIncomeTotalCents,
                assignedTotalCents, remainingToAssignCents, totalSpentCents, billsBeforePaydayCents,
                cashAfterBillsCents, daysUntilPayday, nextPayday, categories, true, null, "");
    }

    private BudgetSummary(int budgetMonthId, String month, int includedAccountBalanceCents,
            int plannedIncomeTotalCents, int assignedTotalCents, int remainingToAssignCents,
            int totalSpentCents, Integer billsBeforePaydayCents, Integer cashAfterBillsCents,
            Integer daysUntilPayday, String nextPayday, List<BudgetCategory> categories,
            boolean forecastAvailable, Boolean lowCushion, String asOf) {
        this.budgetMonthId = budgetMonthId;
        this.month = month;
        this.includedAccountBalanceCents = includedAccountBalanceCents;
        this.plannedIncomeTotalCents = plannedIncomeTotalCents;
        this.assignedTotalCents = assignedTotalCents;
        this.remainingToAssignCents = remainingToAssignCents;
        this.totalSpentCents = totalSpentCents;
        this.billsBeforePaydayCents = billsBeforePaydayCents;
        this.cashAfterBillsCents = cashAfterBillsCents;
        this.daysUntilPayday = daysUntilPayday;
        this.nextPayday = nextPayday;
        this.forecastAvailable = forecastAvailable;
        this.lowCushion = lowCushion;
        this.asOf = asOf;
        this.categories = Collections.unmodifiableList(new ArrayList<>(categories));
    }

    public BudgetSummary(
            int budgetMonthId,
            String month,
            int includedAccountBalanceCents,
            int billsBeforePaydayCents,
            int cashAfterBillsCents,
            int daysUntilPayday,
            String nextPayday,
            List<BudgetCategory> categories
    ) {
        this(
                budgetMonthId,
                month,
                includedAccountBalanceCents,
                0,
                0,
                0,
                0,
                billsBeforePaydayCents,
                cashAfterBillsCents,
                daysUntilPayday,
                nextPayday,
                categories
        );
    }

    public static BudgetSummary fromJson(JSONObject json) {
        JSONArray categoryArray = json.optJSONArray("categories");
        ArrayList<BudgetCategory> categories = new ArrayList<>();
        if (categoryArray != null) {
            for (int i = 0; i < categoryArray.length(); i++) {
                categories.add(BudgetCategory.fromJson(categoryArray.optJSONObject(i)));
            }
        }
        boolean forecastAvailable = json.optBoolean("forecast_available", !json.isNull("next_payday"));
        return new BudgetSummary(
                json.optInt("budget_month_id"),
                json.optString("month", "Unknown month"),
                JsonMoney.cents(json, "included_account_balance_cents"),
                JsonMoney.cents(json, json.has("planned_income_total_cents") ? "planned_income_total_cents" : "income_available_cents"),
                JsonMoney.cents(json, json.has("assigned_total_cents") ? "assigned_total_cents" : "planned_cents"),
                JsonMoney.cents(json, json.has("remaining_to_assign_cents") ? "remaining_to_assign_cents" : "unassigned_cents"),
                JsonMoney.cents(json, "total_spent_cents"),
                forecastAvailable ? JsonMoney.cents(json, "bills_before_payday_cents") : null,
                forecastAvailable ? JsonMoney.cents(json, "cash_after_bills_cents") : null,
                forecastAvailable ? json.optInt("days_until_payday") : null,
                forecastAvailable ? json.optString("next_payday", "") : "",
                categories,
                forecastAvailable,
                json.opt("low_cushion") instanceof Boolean ? json.optBoolean("low_cushion") : null,
                json.optString("as_of", "")
        );
    }

    public int uncategorizedAttentionCount(List<TransactionDetail> reviewQueue) {
        return reviewQueue == null ? 0 : reviewQueue.size();
    }

    public List<BudgetCategory> categoriesNeedingAttention() {
        ArrayList<BudgetCategory> result = new ArrayList<>();
        for (BudgetCategory category : categories) {
            if (!category.archived && category.remainingCents <= 0) {
                result.add(category);
            }
        }
        return result;
    }

    public boolean hasLowCushion() {
        return Boolean.TRUE.equals(lowCushion);
    }
}
