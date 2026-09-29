package com.familyfinance.app.model;

import org.json.JSONObject;
import org.junit.Test;

import static org.junit.Assert.assertEquals;

public final class TransactionLineTest {
    @Test
    public void explicitNullMerchantUsesTransactionName() throws Exception {
        TransactionLine transaction = TransactionLine.fromJson(data().put("merchant_name", JSONObject.NULL));
        assertEquals("", transaction.merchantName);
        assertEquals("Bank transaction name", transaction.displayName());
    }

    @Test
    public void absentMerchantUsesTransactionName() throws Exception {
        assertEquals("Bank transaction name", TransactionLine.fromJson(data()).displayName());
    }

    @Test
    public void availableMerchantRemainsTheDisplayName() throws Exception {
        assertEquals("Merchant name", TransactionLine.fromJson(data().put("merchant_name", "Merchant name")).displayName());
    }

    private JSONObject data() throws Exception {
        return new JSONObject().put("amount_cents", -1000).put("name", "Bank transaction name");
    }
}
