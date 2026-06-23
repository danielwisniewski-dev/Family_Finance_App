package com.familyfinance.app.state;

import com.familyfinance.app.model.BudgetCategory;
import com.familyfinance.app.model.TransactionDetail;

import java.util.ArrayList;
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
}
