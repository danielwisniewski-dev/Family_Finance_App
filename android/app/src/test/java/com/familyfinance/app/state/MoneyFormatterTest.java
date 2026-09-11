package com.familyfinance.app.state;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

public final class MoneyFormatterTest {
    @Test
    public void parsesDollarAmountsToCents() {
        assertEquals(4250, MoneyFormatter.parseDollarAmountToCents("42.50"));
        assertEquals(120000, MoneyFormatter.parseDollarAmountToCents("$1,200.00"));
        assertEquals(29, MoneyFormatter.parseDollarAmountToCents("0.29"));
        assertEquals(50, MoneyFormatter.parseDollarAmountToCents(".50"));
        assertEquals(0, MoneyFormatter.parseDollarAmountToCents(""));
        assertEquals(-125, MoneyFormatter.parseDollarAmountToCents("-1.25"));
        assertEquals(Integer.MAX_VALUE, MoneyFormatter.parseDollarAmountToCents("21474836.47"));
        assertEquals(Integer.MIN_VALUE, MoneyFormatter.parseDollarAmountToCents("-21474836.48"));
    }

    @Test
    public void rejectsRoundingOverflowAndAmbiguousAmounts() {
        for (String input : new String[]{"1.005", "0.001", "NaN", "Infinity", "1e3", "1,23.45",
                "12$34", "21474836.48", "-21474836.49", "999999999999999999999999"}) {
            assertThrows(input, NumberFormatException.class, () -> MoneyFormatter.parseDollarAmountToCents(input));
        }
    }

    @Test
    public void formatsLargeAndNegativeCentValuesExactly() {
        assertEquals("21474836.47", MoneyFormatter.dollarsWithoutSymbol(Integer.MAX_VALUE));
        assertEquals("-21474836.48", MoneyFormatter.dollarsWithoutSymbol(Integer.MIN_VALUE));
        assertEquals("$42,949,672.94", MoneyFormatter.dollars(4294967294L));
    }
}
