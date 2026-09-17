package com.familyfinance.app.state;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;

/** Personal check-in history; independent of budget and bank records. */
public final class CheckInStreak {
    public final int days;
    public final int bestDays;

    private CheckInStreak(int days, int bestDays) {
        this.days = days;
        this.bestDays = bestDays;
    }

    public static CheckInStreak record(LocalDate today, String lastDate, int currentDays, int bestDays) {
        // Seed the record from the old app's saved streak before a missed day can reset it.
        int knownBest = Math.max(bestDays, currentDays);
        int days = 1;
        try {
            LocalDate last = LocalDate.parse(lastDate);
            if (today.equals(last)) {
                days = Math.max(1, currentDays);
            } else if (today.minusDays(1).equals(last)) {
                days = Math.max(0, currentDays) + 1;
            }
        } catch (DateTimeParseException ignored) {
            // First check-in, or an unreadable old date: start today and keep the record.
        }
        return new CheckInStreak(days, Math.max(knownBest, days));
    }
}
