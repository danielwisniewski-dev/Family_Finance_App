package com.familyfinance.app.state;

import java.math.BigDecimal;
import java.text.NumberFormat;
import java.util.Locale;

public final class MoneyFormatter {
    private MoneyFormatter() {
    }

    public static String dollars(long cents) {
        NumberFormat format = NumberFormat.getCurrencyInstance(Locale.US);
        return format.format(BigDecimal.valueOf(cents, 2));
    }

    public static String dollarsWithoutSymbol(int cents) {
        return BigDecimal.valueOf(cents, 2).toPlainString();
    }

    public static int parseDollarAmountToCents(String value) {
        if (value == null || value.trim().isEmpty()) {
            return 0;
        }
        String normalized = value.trim();
        if (!normalized.matches("[+-]?\\$?(?:(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\\.[0-9]{1,2})?|\\.[0-9]{1,2})")) {
            throw new NumberFormatException("Enter dollars with at most two decimal places.");
        }
        try {
            return new BigDecimal(normalized.replace("$", "").replace(",", ""))
                    .movePointRight(2).intValueExact();
        } catch (ArithmeticException exception) {
            throw new NumberFormatException("Amount is outside the supported range.");
        }
    }
}
