package com.familyfinance.app.model;

import org.json.JSONObject;
import org.junit.Test;

import static org.junit.Assert.*;

public final class JsonMoneyTest {
    @Test
    public void preservesPositiveZeroNegativeAndBoundaryCents() throws Exception {
        for (int value : new int[]{0, 29, -125, Integer.MAX_VALUE, Integer.MIN_VALUE}) {
            assertEquals(value, JsonMoney.cents(new JSONObject().put("amount_cents", value), "amount_cents"));
        }
    }

    @Test
    public void invalidFinancialResponseNeverBecomesZeroOrWraps() throws Exception {
        for (Object value : new Object[]{JSONObject.NULL, "42", true, 1.5, 2147483648L, -2147483649L}) {
            JSONObject json = new JSONObject().put("amount_cents", value);
            assertThrows(IllegalArgumentException.class, () -> JsonMoney.cents(json, "amount_cents"));
        }
        assertThrows(IllegalArgumentException.class, () -> JsonMoney.cents(new JSONObject(), "amount_cents"));
    }
}
