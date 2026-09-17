package com.familyfinance.app.state;

import com.familyfinance.app.model.TransactionDetail;
import org.json.JSONObject;
import org.junit.Test;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import static org.junit.Assert.*;

public final class SelectedCategoryAssignerTest {
    private static TransactionDetail transaction(int id, int amount, boolean reviewed, boolean ignored,
            Integer category, String status) throws Exception {
        JSONObject row = new JSONObject().put("id", id).put("amount_cents", amount)
                .put("occurred_on", "2026-09-17").put("name", "Store " + id)
                .put("reviewed", reviewed).put("ignored", ignored);
        return TransactionDetail.fromJson(new JSONObject().put("transaction", row)
                .put("final_category_id", category == null ? JSONObject.NULL : category)
                .put("categorization_status", status).put("needs_review", !reviewed || category == null));
    }

    private static final class FakeGateway implements SelectedCategoryAssigner.Gateway {
        final Map<Integer, TransactionDetail> current = new HashMap<>();
        final List<Integer> saves = new ArrayList<>();
        int failOn;
        boolean saveBeforeFailure;
        int category;

        @Override public TransactionDetail load(int id) { return current.get(id); }
        @Override public void assignAndReview(int id, int categoryId) throws Exception {
            if (id == failOn && !saveBeforeFailure) throw new IOException("Offline");
            saves.add(id);
            category = categoryId;
            if (id == failOn) throw new IOException("Response lost after saving");
        }
    }

    @Test public void assignsOnlyExplicitSelectionsAndDoesNotSendDuplicates() throws Exception {
        TransactionDetail first = transaction(1, -1200, false, false, null, "uncategorized");
        TransactionDetail second = transaction(2, -800, false, false, 5, "rule");
        FakeGateway gateway = new FakeGateway();
        gateway.current.put(1, first);
        gateway.current.put(2, second);
        gateway.current.put(3, transaction(3, -100, false, false, null, "uncategorized"));
        SelectedCategoryAssigner.Result result = SelectedCategoryAssigner.assign(Arrays.asList(first, second, first), 40, gateway);
        assertEquals(Arrays.asList(1, 2), gateway.saves);
        assertEquals(40, gateway.category);
        assertEquals(2, result.confirmed);
        assertNull(result.error);
        assertFalse(result.changed);
    }

    @Test public void stopsOnNetworkFailureAndReportsOnlyConfirmedSaves() throws Exception {
        for (boolean serverSaved : new boolean[]{false, true}) {
            TransactionDetail first = transaction(1, -1200, false, false, null, "uncategorized");
            TransactionDetail second = transaction(2, -800, false, false, null, "uncategorized");
            TransactionDetail third = transaction(3, -500, false, false, null, "uncategorized");
            FakeGateway gateway = new FakeGateway();
            gateway.current.put(1, first);
            gateway.current.put(2, second);
            gateway.current.put(3, third);
            gateway.failOn = 2;
            gateway.saveBeforeFailure = serverSaved;
            SelectedCategoryAssigner.Result result = SelectedCategoryAssigner.assign(Arrays.asList(first, second, third), 40, gateway);
            assertEquals(1, result.confirmed);
            assertNotNull(result.error);
            assertFalse(gateway.saves.contains(3));
            assertEquals(serverSaved ? Arrays.asList(1, 2) : Arrays.asList(1), gateway.saves);
        }
    }

    @Test public void stopsWhenAnotherReviewOrBankUpdateChangesASelection() throws Exception {
        TransactionDetail selected = transaction(1, -1200, false, false, null, "uncategorized");
        for (TransactionDetail changed : Arrays.asList(
                transaction(1, -1400, false, false, null, "uncategorized"),
                transaction(1, -1200, true, false, 20, "manual"),
                transaction(1, -1200, false, true, null, "ignored"),
                transaction(1, -1200, false, false, null, "split"),
                transaction(1, -1200, false, false, 20, "rule"))) {
            FakeGateway gateway = new FakeGateway();
            gateway.current.put(1, changed);
            SelectedCategoryAssigner.Result result = SelectedCategoryAssigner.assign(Arrays.asList(selected), 40, gateway);
            assertTrue(result.changed);
            assertEquals(0, result.confirmed);
            assertTrue(gateway.saves.isEmpty());
        }
    }

    @Test public void refundsSplitsAndReviewedAssignmentsStayOutOfGroupSelection() throws Exception {
        assertFalse(TransactionReviewState.canAssignTogether(transaction(1, 1200, false, false, null, "uncategorized")));
        assertFalse(TransactionReviewState.canAssignTogether(transaction(1, -1200, false, false, null, "split")));
        assertFalse(TransactionReviewState.canAssignTogether(transaction(1, -1200, true, false, 40, "manual")));
        assertFalse(TransactionReviewState.canAssignTogether(transaction(1, -1200, false, true, null, "ignored")));
        assertTrue(TransactionReviewState.canAssignTogether(transaction(1, -1200, true, false, null, "uncategorized")));
    }

    @Test public void confirmationIsOnlyOfferedForUnreviewedExistingAllocationsOrInflows() throws Exception {
        assertTrue(TransactionReviewState.canConfirmExisting(transaction(1, -1200, false, false, 40, "rule")));
        assertTrue(TransactionReviewState.canConfirmExisting(transaction(1, -1200, false, false, 40, "manual")));
        assertTrue(TransactionReviewState.canConfirmExisting(transaction(1, 1200, false, false, null, "uncategorized")));
        assertTrue(TransactionReviewState.canConfirmExisting(transaction(1, -1200, false, false, null, "split")));
        assertFalse(TransactionReviewState.canConfirmExisting(transaction(1, -1200, false, false, null, "uncategorized")));
        assertFalse(TransactionReviewState.canConfirmExisting(transaction(1, -1200, true, false, 40, "manual")));
        assertFalse(TransactionReviewState.canConfirmExisting(transaction(1, -1200, false, true, 40, "manual")));
    }
}
