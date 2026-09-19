package com.familyfinance.app.state;

import java.time.DateTimeException;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.YearMonth;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Locale;

/** Display formatting only; sync dates come from saved backend data. */
public final class DashboardText {
    private static final DateTimeFormatter MONTH = DateTimeFormatter.ofPattern("MMM uuuu", Locale.US);
    private static final DateTimeFormatter SYNC = DateTimeFormatter.ofPattern("MMM d, h:mm a", Locale.US);

    private DashboardText() { }

    public static String budgetMonth(String month) {
        if (month == null || month.trim().isEmpty()) return "Unknown month";
        try {
            return september(YearMonth.parse(month).format(MONTH));
        } catch (DateTimeException ignored) {
            return month;
        }
    }

    public static String lastBankSync(String transactionsCheckedAt, String balancesCheckedAt, ZoneId zone) {
        Instant transactions = timestamp(transactionsCheckedAt);
        if (transactions != null) return "Last sync: " + september(SYNC.format(transactions.atZone(zone)));
        Instant balances = timestamp(balancesCheckedAt);
        if (balances != null) return "Balance sync: " + september(SYNC.format(balances.atZone(zone)));
        return "Last sync: unavailable";
    }

    private static Instant timestamp(String value) {
        if (value == null || value.trim().isEmpty()) return null;
        String normalized = value.trim().replace(' ', 'T');
        try {
            return OffsetDateTime.parse(normalized).toInstant();
        } catch (DateTimeException ignored) {
            try {
                // SQLite CURRENT_TIMESTAMP is UTC, even though it has no offset suffix.
                return LocalDateTime.parse(normalized).toInstant(ZoneOffset.UTC);
            } catch (DateTimeException invalid) {
                return null;
            }
        }
    }

    private static String september(String value) {
        return value.replace("Sep ", "Sept ");
    }
}
