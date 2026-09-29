package com.familyfinance.app.state;

import com.familyfinance.app.model.TransactionAssignment;
import com.familyfinance.app.model.TransactionDetail;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;

public final class TransactionReviewState {
    private TransactionReviewState() { }

    private static final Comparator<TransactionDetail> NEWEST_FIRST = Comparator
            .comparing((TransactionDetail detail) -> detail.transaction.occurredOn,
                    Comparator.nullsLast(Comparator.reverseOrder()))
            .thenComparing(Comparator.comparingInt((TransactionDetail detail) -> detail.transaction.id).reversed());

    public static boolean hasAssignedCategory(TransactionDetail detail) {
        if (detail.finalCategoryId != null) return true; // Includes a posted refund's category.
        for (TransactionAssignment assignment : detail.assignments) {
            if (assignment.active) return true;
        }
        return false;
    }

    public static List<TransactionDetail> newestFirst(List<TransactionDetail> transactions) {
        ArrayList<TransactionDetail> ordered = new ArrayList<>(transactions);
        ordered.sort(NEWEST_FIRST);
        return ordered;
    }

    public static List<TransactionDetail> reviewOrder(List<TransactionDetail> transactions) {
        ArrayList<TransactionDetail> ordered = new ArrayList<>(transactions);
        ordered.sort(Comparator.comparingInt((TransactionDetail detail) -> hasAssignedCategory(detail) ? 0 : 1)
                .thenComparing(NEWEST_FIRST));
        return ordered;
    }

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
