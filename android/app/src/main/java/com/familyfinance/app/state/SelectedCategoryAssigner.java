package com.familyfinance.app.state;

import com.familyfinance.app.model.TransactionDetail;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Uses the existing per-transaction API and reports only confirmed saves. */
public final class SelectedCategoryAssigner {
    public interface Gateway {
        TransactionDetail load(int transactionId) throws Exception;
        void assignAndReview(int transactionId, int categoryId) throws Exception;
    }

    public static final class Result {
        public final int confirmed;
        public final Exception error;
        public final boolean changed;

        private Result(int confirmed, Exception error, boolean changed) {
            this.confirmed = confirmed;
            this.error = error;
            this.changed = changed;
        }
    }

    private SelectedCategoryAssigner() { }

    public static Result assign(List<TransactionDetail> selected, int categoryId, Gateway gateway) {
        int confirmed = 0;
        Set<Integer> seen = new HashSet<>();
        for (TransactionDetail detail : selected) {
            if (!seen.add(detail.transaction.id)) continue;
            try {
                if (!TransactionReviewState.matchesSelection(detail, gateway.load(detail.transaction.id))) {
                    return new Result(confirmed, null, true);
                }
                gateway.assignAndReview(detail.transaction.id, categoryId);
                confirmed++;
            } catch (Exception error) {
                // A response can be lost after a successful save. Never auto-retry or claim a rollback.
                return new Result(confirmed, error, false);
            }
        }
        return new Result(confirmed, null, false);
    }
}
