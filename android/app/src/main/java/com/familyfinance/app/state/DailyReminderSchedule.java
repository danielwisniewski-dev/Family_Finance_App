package com.familyfinance.app.state;

import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZonedDateTime;

public final class DailyReminderSchedule {
    private DailyReminderSchedule() { }

    public static Instant nextAlarm(ZonedDateTime now, LocalTime time, Instant lastCheck, String lastReminderDay) {
        LocalDate today = now.toLocalDate();
        Instant todayAlarm = today.atTime(time).atZone(now.getZone()).toInstant();
        if (todayAlarm.isAfter(now.toInstant()) && !handledToday(now, lastCheck, lastReminderDay)) {
            return todayAlarm;
        }
        return today.plusDays(1).atTime(time).atZone(now.getZone()).toInstant();
    }

    public static boolean shouldRemind(ZonedDateTime now, LocalTime time, Instant alarm,
                                       Instant lastCheck, String lastReminderDay) {
        Instant expected = now.toLocalDate().atTime(time).atZone(now.getZone()).toInstant();
        return alarm.equals(expected) && !alarm.isAfter(now.toInstant())
                && !handledToday(now, lastCheck, lastReminderDay);
    }

    private static boolean handledToday(ZonedDateTime now, Instant lastCheck, String lastReminderDay) {
        LocalDate today = now.toLocalDate();
        return today.toString().equals(lastReminderDay)
                || (lastCheck != null && today.equals(lastCheck.atZone(now.getZone()).toLocalDate()));
    }
}
