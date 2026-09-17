package com.familyfinance.app.state;

import org.junit.Test;
import java.time.LocalDate;
import java.util.HashSet;
import java.util.Set;
import static org.junit.Assert.*;

public final class CheckInStreakTest {
    private final LocalDate today = LocalDate.of(2026, 9, 17);

    @Test
    public void firstCheckInStartsAtOne() {
        CheckInStreak streak = CheckInStreak.record(today, "", 0, 0);
        assertEquals(1, streak.days);
        assertEquals(1, streak.bestDays);
    }

    @Test
    public void upgradeSeedsBestFromExistingStreakEvenOnSameDay() {
        CheckInStreak streak = CheckInStreak.record(today, today.toString(), 9, 0);
        assertEquals(9, streak.days);
        assertEquals(9, streak.bestDays);
    }

    @Test
    public void repeatedCheckInsDoNotAddDays() {
        CheckInStreak first = CheckInStreak.record(today, today.minusDays(1).toString(), 5, 12);
        CheckInStreak repeated = CheckInStreak.record(today, today.toString(), first.days, first.bestDays);
        assertEquals(6, repeated.days);
        assertEquals(12, repeated.bestDays);
    }

    @Test
    public void missedDayOnUpgradeKeepsOldRecord() {
        CheckInStreak streak = CheckInStreak.record(today, today.minusDays(2).toString(), 9, 0);
        assertEquals(1, streak.days);
        assertEquals(9, streak.bestDays);
    }

    @Test
    public void bestSurvivesMultipleNewStreaksAndIncreasesWhenBeaten() {
        CheckInStreak reset = CheckInStreak.record(today, today.minusDays(3).toString(), 2, 12);
        assertEquals(1, reset.days);
        assertEquals(12, reset.bestDays);
        CheckInStreak record = CheckInStreak.record(today, today.minusDays(1).toString(), 12, 12);
        assertEquals(13, record.days);
        assertEquals(13, record.bestDays);
    }

    @Test
    public void streakContinuesAcrossYearAndLeapDay() {
        assertEquals(8, CheckInStreak.record(LocalDate.of(2027, 1, 1), "2026-12-31", 7, 7).days);
        assertEquals(8, CheckInStreak.record(LocalDate.of(2028, 3, 1), "2028-02-29", 7, 7).days);
    }

    @Test
    public void unreadableOrFutureDateCannotEarnExtraDaysOrEraseBest() {
        for (String date : new String[]{"bad date", today.plusDays(1).toString()}) {
            CheckInStreak streak = CheckInStreak.record(today, date, 3, 10);
            assertEquals(1, streak.days);
            assertEquals(10, streak.bestDays);
        }
    }

    @Test
    public void encouragementStaysSameForTheDayAndCyclesThroughFortyUniqueMessages() {
        Set<String> messages = new HashSet<>();
        for (int day = 0; day < 40; day++) {
            LocalDate date = today.plusDays(day);
            String message = EncouragementMessages.forDate(date);
            assertFalse(message.trim().isEmpty());
            assertEquals(message, EncouragementMessages.forDate(LocalDate.parse(date.toString())));
            assertTrue(messages.add(message));
        }
        assertEquals(EncouragementMessages.forDate(today), EncouragementMessages.forDate(today.plusDays(40)));
    }
}
