package com.familyfinance.app.state;

import com.familyfinance.app.model.TransactionAssignment;
import com.familyfinance.app.model.TransactionDetail;
import java.util.Objects;

public final class TransactionReviewState {
    private TransactionReviewState() { }

    public static boolean canAssignTogether(TransactionDetail detail) {
        return detail.needsReview && !detail.transaction.ignored
                && detail.transaction.amountCents < 0 && !detail.isSplit();
    }

    public static boolean canConfirmExisting(TransactionDetail detail) {
        return !detail.transaction.reviewed && !detail.transaction.ignored
                && (detail.finalCategoryId != null || detail.isSplit() || detail.transaction.amountCents >= 0);
    }

    public static boolean matchesSelection(TransactionDetail selected, TransactionDetail current) {
        if (!canAssignTogether(selected) || !canAssignTogether(current)
                || selected.transaction.id != current.transaction.id
                || selected.transaction.amountCents != current.transaction.amountCents
                || selected.transaction.pending != current.transaction.pending
                || selected.transaction.reviewed != current.transaction.reviewed
                || !Objects.equals(selected.transaction.occurredOn, current.transaction.occurredOn)
                || !Objects.equals(selected.transaction.displayName(), current.transaction.displayName())
                || !Objects.equals(selected.finalCategoryId, current.finalCategoryId)
                || selected.assignments.size() != current.assignments.size()) return false;
        for (int i = 0; i < selected.assignments.size(); i++) {
            TransactionAssignment before = selected.assignments.get(i);
            TransactionAssignment after = current.assignments.get(i);
            if (before.id != after.id || before.categoryId != after.categoryId
                    || before.amountCents != after.amountCents || !Objects.equals(before.source, after.source)) return false;
        }
        return true;
    }
}
