package com.familyfinance.app.model;

import org.json.JSONObject;

import java.math.BigDecimal;

/** Financial responses must contain exact cents; absent or invalid values are not zero. */
final class JsonMoney {
    private JsonMoney() { }

    static int cents(JSONObject json, String key) {
        Object value = json == null ? null : json.opt(key);
        if (!(value instanceof Number)) {
            throw new IllegalArgumentException("Backend returned an invalid money value. Reload and check the backend version.");
        }
        try {
            return new BigDecimal(value.toString()).intValueExact();
        } catch (ArithmeticException | NumberFormatException exception) {
            throw new IllegalArgumentException("Backend returned a money value outside the supported range.");
        }
    }
}
