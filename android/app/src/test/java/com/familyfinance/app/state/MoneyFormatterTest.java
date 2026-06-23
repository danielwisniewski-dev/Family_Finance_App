package com.familyfinance.app.state;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

public final class MoneyFormatterTest {
    @Test
    public void parsesDollarAmountsToCents() {
        assertEquals(4250, MoneyFormatter.parseDollarAmountToCents("42.50"));
        assertEquals(120000, MoneyFormatter.parseDollarAmountToCents("$1,200.00"));
    }
}
