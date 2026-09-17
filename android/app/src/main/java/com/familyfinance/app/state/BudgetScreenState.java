package com.familyfinance.app.state;

import com.familyfinance.app.model.BudgetCategory;
import com.familyfinance.app.model.TransactionDetail;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

public final class BudgetScreenState {
    private BudgetScreenState() {
    }

    public static List<TransactionDetail> transactionsForCategory(
            int categoryId,
            List<TransactionDetail> transactions
    ) {
        ArrayList<TransactionDetail> result = new ArrayList<>();
        if (transactions == null) {
            return result;
        }
        for (TransactionDetail detail : transactions) {
            if (detail.finalCategoryId != null && detail.finalCategoryId == categoryId) {
                result.add(detail);
                continue;
            }
            for (int i = 0; i < detail.assignments.size(); i++) {
                if (detail.assignments.get(i).categoryId == categoryId) {
                    result.add(detail);
                    break;
                }
            }
        }
        return result;
    }

    public static BudgetCategory findCategory(int categoryId, List<BudgetCategory> categories) {
        if (categories == null) {
            return null;
        }
        for (BudgetCategory category : categories) {
            if (category.id == categoryId) {
                return category;
            }
        }
        return null;
    }

    public static List<BudgetCategory> activeCategories(List<BudgetCategory> categories) {
        ArrayList<BudgetCategory> result = new ArrayList<>();
        if (categories != null) {
            for (BudgetCategory category : categories) {
                if (!category.archived) {
                    result.add(category);
                }
            }
        }
        return result;
    }

    public static List<BudgetCategory> sortedCategoryChoices(List<BudgetCategory> categories) {
        List<BudgetCategory> result = activeCategories(categories);
        result.sort(Comparator.comparing((BudgetCategory category) -> category.name, String.CASE_INSENSITIVE_ORDER)
                .thenComparingInt(category -> category.id));
        return result;
    }

    public static BudgetCategory categoryChoice(List<BudgetCategory> choices, int spinnerPosition) {
        // Position zero is the prompt, never a financial category.
        int index = spinnerPosition - 1;
        return index >= 0 && index < choices.size() ? choices.get(index) : null;
    }

    public static String splitValidationMessage(int transactionTotalCents, List<Integer> splitAmountsCents) {
        if (splitAmountsCents == null || splitAmountsCents.size() < 2) {
            return "Use at least two split lines.";
        }
        long total = 0;
        for (Integer amount : splitAmountsCents) {
            if (amount == null || amount <= 0) {
                return "Split amounts must be positive.";
            }
            total += amount;
        }
        if (total != transactionTotalCents) {
            return "Split total must equal the transaction amount.";
        }
        return "";
    }
}
