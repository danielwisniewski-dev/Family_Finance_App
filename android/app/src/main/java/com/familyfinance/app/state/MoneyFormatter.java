package com.familyfinance.app.state;

import java.text.NumberFormat;
import java.util.Locale;

public final class MoneyFormatter {
    private MoneyFormatter() {
    }

    public static String dollars(int cents) {
        NumberFormat format = NumberFormat.getCurrencyInstance(Locale.US);
        return format.format(cents / 100.0);
    }

    public static String dollarsWithoutSymbol(int cents) {
        return String.format(Locale.US, "%.2f", cents / 100.0);
    }

    public static int parseDollarAmountToCents(String value) {
        if (value == null || value.trim().isEmpty()) {
            return 0;
        }
        String normalized = value.trim().replace("$", "").replace(",", "");
        return (int) Math.round(Double.parseDouble(normalized) * 100.0);
    }
}
