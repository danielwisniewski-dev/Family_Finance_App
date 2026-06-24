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
    public final int billsBeforePaydayCents;
    public final int cashAfterBillsCents;
    public final int daysUntilPayday;
    public final String nextPayday;
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
        return new BudgetSummary(
                json.optInt("budget_month_id"),
                json.optString("month", "Unknown month"),
                json.optInt("included_account_balance_cents"),
                json.optInt("planned_income_total_cents", json.optInt("income_available_cents")),
                json.optInt("assigned_total_cents", json.optInt("planned_cents")),
                json.optInt("remaining_to_assign_cents", json.optInt("unassigned_cents")),
                json.optInt("total_spent_cents"),
                json.optInt("bills_before_payday_cents"),
                json.optInt("cash_after_bills_cents"),
                json.optInt("days_until_payday"),
                json.optString("next_payday", ""),
                categories
        );
    }

    public int uncategorizedAttentionCount(List<TransactionDetail> reviewQueue) {
        return reviewQueue == null ? 0 : reviewQueue.size();
    }

    public List<BudgetCategory> categoriesNeedingAttention() {
        ArrayList<BudgetCategory> result = new ArrayList<>();
        for (BudgetCategory category : categories) {
            if (category.isOverspent() || category.remainingCents <= 0) {
                result.add(category);
            }
        }
        return result;
    }

    public boolean hasLowCushion() {
        if (daysUntilPayday <= 0) {
            return cashAfterBillsCents < 0;
        }
        return cashAfterBillsCents / Math.max(daysUntilPayday, 1) < 5_000;
    }
}
