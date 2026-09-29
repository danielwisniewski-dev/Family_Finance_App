package com.familyfinance.app.state;

import org.json.JSONObject;
import org.junit.Test;

import static org.junit.Assert.*;

public final class PendingFundActionTest {
    private JSONObject contribution() throws Exception {
        return new JSONObject().put("budget_month_id", 12).put("kind", "contribution")
                .put("amount_cents", 2500).put("occurred_on", "2026-09-23").put("note", "From this payday");
    }

    @Test
    public void lostResponseRetryAndAppRestartKeepTheExactRequest() throws Exception {
        PendingFundAction action = PendingFundAction.create(7, false, contribution());
        PendingFundAction restored = PendingFundAction.restore(action.serialize());
        assertEquals(action.payload().getString("idempotency_key"), restored.payload().getString("idempotency_key"));
        assertEquals(action.serialize(), restored.serialize());
        assertEquals(7, restored.fundId);
        assertFalse(restored.transfer);
    }

    @Test
    public void callerCannotChangeAnAlreadySubmittedRequest() throws Exception {
        JSONObject input = contribution();
        PendingFundAction action = PendingFundAction.create(7, false, input);
        input.put("amount_cents", 9999);
        action.payload().put("amount_cents", 8888);
        assertEquals(2500, action.payload().getInt("amount_cents"));
    }

    @Test
    public void separateConfirmedContributionsUseDifferentKeys() throws Exception {
        PendingFundAction first = PendingFundAction.create(7, false, contribution());
        PendingFundAction next = PendingFundAction.create(7, false, contribution());
        assertNotEquals(first.payload().getString("idempotency_key"), next.payload().getString("idempotency_key"));
    }

    @Test
    public void transferRetainsDestinationAndEndpointAfterRestart() throws Exception {
        JSONObject body = contribution().put("target_fund_id", 9);
        body.remove("kind");
        PendingFundAction restored = PendingFundAction.restore(PendingFundAction.create(7, true, body).serialize());
        assertTrue(restored.transfer);
        assertEquals(9, restored.payload().getInt("target_fund_id"));
    }
}
