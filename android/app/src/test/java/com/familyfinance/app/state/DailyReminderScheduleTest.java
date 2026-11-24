package com.familyfinance.app.state;

import org.junit.Test;

import java.time.Instant;
import java.time.LocalTime;
import java.time.ZonedDateTime;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public final class DailyReminderScheduleTest {
    private static final LocalTime EVENING = LocalTime.of(19, 0);

    @Test
    public void priorDayCheckAllowsTodayButTodaysCheckOrReminderSkipsIt() {
        ZonedDateTime now = ZonedDateTime.parse("2026-11-24T16:00-05:00[America/New_York]");
        Instant yesterday = now.minusDays(1).toInstant();
        assertEquals(Instant.parse("2026-11-25T00:00:00Z"),
                DailyReminderSchedule.nextAlarm(now, EVENING, yesterday, ""));
        assertEquals(Instant.parse("2026-11-26T00:00:00Z"),
                DailyReminderSchedule.nextAlarm(now, EVENING, now.minusHours(2).toInstant(), ""));
        assertEquals(Instant.parse("2026-11-26T00:00:00Z"),
                DailyReminderSchedule.nextAlarm(now, EVENING, yesterday, "2026-11-24"));
    }

    @Test
    public void deliveryRechecksActivityAndRejectsEarlyStaleChangedAndDuplicateAlarms() {
        ZonedDateTime now = ZonedDateTime.parse("2026-11-24T19:20-05:00[America/New_York]");
        Instant due = now.minusMinutes(20).toInstant();
        assertTrue(DailyReminderSchedule.shouldRemind(now, EVENING, due, null, ""));
        assertFalse(DailyReminderSchedule.shouldRemind(now, EVENING, due, now.minusMinutes(10).toInstant(), ""));
        assertFalse(DailyReminderSchedule.shouldRemind(now, EVENING, due, null, "2026-11-24"));
        assertFalse(DailyReminderSchedule.shouldRemind(now.minusHours(1), EVENING, due, null, ""));
        assertFalse(DailyReminderSchedule.shouldRemind(now.plusDays(1), EVENING, due, null, ""));
        assertFalse(DailyReminderSchedule.shouldRemind(now, EVENING.minusHours(1), due, null, ""));
    }

    @Test
    public void rebasingAfterClockChangesSkipsMissedTimeAndKeepsLocalHourAcrossDaylightSaving() {
        ZonedDateTime after = ZonedDateTime.parse("2026-03-07T19:20-05:00[America/New_York]");
        Instant next = DailyReminderSchedule.nextAlarm(after, EVENING, null, "");
        assertEquals(Instant.parse("2026-03-08T23:00:00Z"), next);
        ZonedDateTime afterTravel = ZonedDateTime.parse("2026-03-08T16:00-07:00[America/Los_Angeles]");
        assertFalse(DailyReminderSchedule.shouldRemind(afterTravel, EVENING, next, null, ""));
        assertEquals(Instant.parse("2026-03-09T02:00:00Z"),
                DailyReminderSchedule.nextAlarm(afterTravel, EVENING, null, ""));
    }
}
