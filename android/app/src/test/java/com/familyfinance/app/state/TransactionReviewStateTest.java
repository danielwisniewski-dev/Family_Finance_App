package com.familyfinance.app.state;

import com.familyfinance.app.model.TransactionDetail;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import static org.junit.Assert.*;

public final class TransactionReviewStateTest {
    private JSONObject data(int id, String occurredOn, int amount, Integer category) throws Exception {
        return new JSONObject().put("transaction", new JSONObject().put("id", id).put("occurred_on", occurredOn)
                .put("amount_cents", amount).put("name", "Synthetic transaction " + id).put("reviewed", false))
                .put("final_category_id", category == null ? JSONObject.NULL : category)
                .put("needs_review", true).put("categorization_status", category == null ? "uncategorized" : "manual");
    }

    private TransactionDetail transaction(int id, String date, Integer category) throws Exception {
        return TransactionDetail.fromJson(data(id, date, -1000, category));
    }

    private List<Integer> ids(List<TransactionDetail> values) {
        List<Integer> result = new ArrayList<>();
        for (TransactionDetail value : values) result.add(value.transaction.id);
        return result;
    }

    @Test
    public void allTransactionsUseNewestDateThenNewestIdRegardlessOfCategorization() throws Exception {
        List<TransactionDetail> source = Arrays.asList(transaction(4, "2026-09-20", 1),
                transaction(1, "2026-09-23", null), transaction(7, "2026-09-23", 1), transaction(9, "2026-08-31", null));
        assertEquals(Arrays.asList(7, 1, 4, 9), ids(TransactionReviewState.newestFirst(source)));
        assertEquals(Arrays.asList(4, 1, 7, 9), ids(source));
    }

    @Test
    public void assignedCategoriesComeBeforeNewerUncategorizedTransactions() throws Exception {
        List<TransactionDetail> source = Arrays.asList(transaction(20, "2026-09-23", null),
                transaction(3, "2026-09-19", 1), transaction(9, "2026-09-21", 1),
                transaction(12, "2026-09-21", 1), transaction(2, "2026-09-22", null));
        assertEquals(Arrays.asList(12, 9, 3, 20, 2), ids(TransactionReviewState.reviewOrder(source)));
        assertEquals(Arrays.asList(20, 3, 9, 12, 2), ids(source));
    }

    @Test
    public void activeSplitAndAppliedRefundBelongWithCategorizedItems() throws Exception {
        JSONObject split = data(4, "2026-09-20", -1000, null).put("categorization_status", "split")
                .put("assignments", new JSONArray().put(assignment(4, 1, true)).put(assignment(4, 2, true)));
        TransactionDetail refund = TransactionDetail.fromJson(data(6, "2026-09-21", 1000, 1)
                .put("categorization_status", "refund"));
        TransactionDetail splitDetail = TransactionDetail.fromJson(split);
        assertTrue(TransactionReviewState.hasAssignedCategory(splitDetail));
        assertTrue(TransactionReviewState.hasAssignedCategory(refund));
        assertEquals(Arrays.asList(6, 4, 10), ids(TransactionReviewState.reviewOrder(Arrays.asList(
                transaction(10, "2026-09-23", null), splitDetail, refund))));
    }

    @Test
    public void suggestionsAndInactiveAssignmentsDoNotClaimACategoryWasApplied() throws Exception {
        TransactionDetail suggestion = TransactionDetail.fromJson(data(4, "2026-09-23", -1000, null)
                .put("suggested_category_id", 1).put("suggestion_source", "merchant_rule"));
        TransactionDetail oldSplit = TransactionDetail.fromJson(data(6, "2026-09-22", -1000, null)
                .put("categorization_status", "split")
                .put("assignments", new JSONArray().put(assignment(6, 1, false))));
        assertFalse(TransactionReviewState.hasAssignedCategory(suggestion));
        assertFalse(TransactionReviewState.hasAssignedCategory(oldSplit));
        assertEquals(Arrays.asList(1, 4, 6), ids(TransactionReviewState.reviewOrder(Arrays.asList(
                suggestion, oldSplit, transaction(1, "2026-09-19", 1)))));
    }

    @Test
    public void unassignedIncomingMoneyStaysInTheSecondGroupDespiteBeingConfirmable() throws Exception {
        TransactionDetail income = TransactionDetail.fromJson(data(9, "2026-09-23", 5000, null));
        assertTrue(TransactionReviewState.canConfirmExisting(income));
        assertFalse(TransactionReviewState.hasAssignedCategory(income));
        assertEquals(Arrays.asList(2, 9, 3, 1), ids(TransactionReviewState.reviewOrder(Arrays.asList(
                income, transaction(1, "2026-09-21", null), transaction(2, "2026-09-19", 1),
                transaction(3, "2026-09-21", null)))));
    }

    @Test
    public void orderingDoesNotFilterReviewedOrIgnoredHistory() throws Exception {
        TransactionDetail reviewed = TransactionDetail.fromJson(data(3, "2026-09-21", -1000, 1)
                .put("transaction", new JSONObject().put("id", 3).put("occurred_on", "2026-09-21")
                        .put("amount_cents", -1000).put("reviewed", true).put("ignored", true)));
        assertEquals(Arrays.asList(4, 3), ids(TransactionReviewState.newestFirst(Arrays.asList(
                reviewed, transaction(4, "2026-09-22", null)))));
        assertTrue(TransactionReviewState.reviewOrder(Collections.emptyList()).isEmpty());
    }

    private JSONObject assignment(int transactionId, int categoryId, boolean active) throws Exception {
        return new JSONObject().put("id", categoryId).put("transaction_id", transactionId)
                .put("category_id", categoryId).put("amount_cents", 500).put("source", "manual").put("active", active);
    }
}
