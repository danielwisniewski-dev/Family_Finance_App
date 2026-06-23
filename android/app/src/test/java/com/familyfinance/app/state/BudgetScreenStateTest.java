package com.familyfinance.app.state;

import com.familyfinance.app.model.BudgetCategory;
import com.familyfinance.app.model.TransactionAssignment;
import com.familyfinance.app.model.TransactionDetail;
import com.familyfinance.app.model.TransactionLine;

import org.junit.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertSame;

public final class BudgetScreenStateTest {
    @Test
    public void findsTransactionsForDirectAndSplitAssignments() {
        TransactionDetail direct = detail(1, 10, Collections.emptyList());
        TransactionDetail split = detail(
                2,
                null,
                Arrays.asList(
                        new TransactionAssignment(1, 2, 10, 1200, "split", true),
                        new TransactionAssignment(2, 2, 11, 800, "split", true)
                )
        );
        TransactionDetail other = detail(3, 12, Collections.emptyList());

        List<TransactionDetail> result = BudgetScreenState.transactionsForCategory(
                10,
                Arrays.asList(direct, split, other)
        );

        assertEquals(2, result.size());
        assertEquals(1, result.get(0).transaction.id);
        assertEquals(2, result.get(1).transaction.id);
    }

    @Test
    public void findsCategoryById() {
        BudgetCategory groceries = new BudgetCategory(10, "Groceries", 50000, 10000, 40000, false);
        BudgetCategory gas = new BudgetCategory(11, "Gas", 15000, 2000, 13000, false);

        assertSame(gas, BudgetScreenState.findCategory(11, Arrays.asList(groceries, gas)));
    }

    private static TransactionDetail detail(
            int id,
            Integer finalCategoryId,
            List<TransactionAssignment> assignments
    ) {
        return new TransactionDetail(
                new TransactionLine(id, -1200, "2026-06-21", "Store", "Store", false, "", false, false, ""),
                assignments,
                finalCategoryId,
                finalCategoryId == null ? "split" : "manual",
                false
        );
    }
}
