package com.familyfinance.app.state;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;

/** Rewards confirmed actions and new check-ins without changing financial or streak state. */
public final class CelebrationPolicy {
    public enum Reward { NONE, SMALL, QUEUE_CLEARED }

    private CelebrationPolicy() { }

    public static Reward reviewReward(boolean confirmedSuccess, boolean hadPending,
                                      boolean queueEmpty, boolean completeBatch) {
        if (!confirmedSuccess || !completeBatch) return Reward.NONE;
        return hadPending && queueEmpty ? Reward.QUEUE_CLEARED : Reward.SMALL;
    }

    /** Returns a message only for a newly earned milestone or an established record beaten. */
    public static String streakMessage(LocalDate today, String previousDate, int previousDays,
                                       int previousBest, CheckInStreak current) {
        if (today == null || previousDate == null || current == null || previousDays < 1) return null;
        try {
            // Same-day redraws, gaps, and invalid/future dates cannot earn a celebration.
            if (!today.minusDays(1).equals(LocalDate.parse(previousDate))) return null;
        } catch (DateTimeParseException ignored) {
            return null;
        }
        if ((long) current.days != (long) previousDays + 1L) return null;
        int days = current.days;
        if (days == 7 || days == 14 || (days >= 30 && days % 30 == 0)) {
            return days + " days of checking in — nicely done!";
        }
        // An upgrade may seed a previously unstored best. That is not a new record.
        if (previousBest > 0 && days > Math.max(previousBest, previousDays)) {
            return "A new personal best: " + days + " days!";
        }
        return null;
    }
}
